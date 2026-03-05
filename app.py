import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import math

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

@st.cache_resource
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    return gspread.authorize(creds)

try:
    gc = get_gsheet_client()
    sh = gc.open_by_key("1-f7O8vH9-7ZGqRgZIiINy17YUywErcK332MzuYyNerQ")
    inv_ws = sh.worksheet("Inventory")
    tasks_ws = sh.worksheet("Tasks")
    arch_ws = sh.worksheet("Archive")
except Exception as e:
    st.error(f"חיבור נכשל: {e}")
    st.stop()

is_admin = st.query_params.get("role") == "admin"
st.title("🍕 מערכת ניהול פיצטה")

menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"] if is_admin else ["המשימות שלי"]
choice = st.sidebar.selectbox("תפריט ניווט", menu)

# --- 1. מנהל: ניהול משימות ---
if choice == "ניהול משימות":
    st.header("🎯 שליחת ספקים לספירה")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    all_suppliers = sorted(df_inv['ספק'].unique())
    selected = st.multiselect("בחר ספקים:", all_suppliers)
    if st.button("שלח משימות ✅"):
        if selected:
            for s in selected:
                tasks_ws.append_row([s, "לביצוע ⏳", datetime.now().strftime("%d/%m %H:%M"), ""])
            st.success("המשימות נשלחו!")

# --- 2. עובד: המשימות שלי (מספרים שלמים בלבד) ---
elif choice == "המשימות שלי":
    st.header("📋 משימות פתוחות")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    if 'סטטוס' in df_tasks.columns:
        pending = df_tasks[df_tasks['סטטוס'] == "לביצוע ⏳"]
        if pending.empty:
            st.info("אין משימות פתוחות.")
        else:
            full_data = inv_ws.get_all_values()
            df_inv = pd.DataFrame(full_data[1:], columns=full_data[0])
            for idx, t_row in pending.iterrows():
                with st.expander(f"ספירה: {t_row['ספק']}", expanded=True):
                    s_prods = df_inv[df_inv['ספק'] == t_row['ספק']]
                    with st.form(key=f"worker_form_{idx}"):
                        current_updates = {}
                        for _, p_row in s_prods.iterrows():
                            p_name = p_row['מוצר']
                            st.write(f"**{p_name}** ({p_row['יחידת מידה']})")
                            
                            # הגדרה כ-int חוסמת נקודה עשרונית
                            val = st.number_input("כמות במלאי (שלם):", min_value=0, step=1, value=0, key=f"in_{idx}_{p_name}")
                            
                            inv_row_idx = df_inv[df_inv['מוצר'] == p_name].index[0] + 2
                            current_updates[inv_row_idx] = val
                            st.divider()
                        
                        if st.form_submit_button(f"💾 שלח ספירת {t_row['ספק']}"):
                            tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                            col_idx = full_data[0].index("מלאי בפועל") + 1
                            updates = []
                            for r_idx, amount in current_updates.items():
                                updates.append({'range': gspread.utils.rowcol_to_a1(r_idx, col_idx), 'values': [[amount]]})
                            inv_ws.batch_update(updates)
                            st.success("המלאי עודכן!")
                            st.rerun()

# --- 3. מנהל: אישור והזמנות (עיגול אוטומטי למעלה) ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור והמרת כמויות להזמנה")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    if 'סטטוס' in df_tasks.columns:
        ready = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
        if not ready.empty:
            df_inv = pd.DataFrame(inv_ws.get_all_records())
            for idx, t_row in ready.iterrows():
                s = t_row['ספק']
                st.subheader(f"בדיקת הזמנה: {s}")
                s_prods = df_inv[df_inv['ספק'] == s]
                order_lines = []
                with st.form(key=f"admin_form_{idx}"):
                    for _, p_row in s_prods.iterrows():
                        p_name = p_row['מוצר']
                        try:
                            stock = float(p_row['מלאי בפועל']) if p_row['מלאי בפועל'] != "" else 0.0
                            target = float(p_row['יעד השלמה']) if p_row['יעד השלמה'] != "" else 0.0
                            min_val = float(p_row['מינימום להזמנה']) if p_row.get('מינימום להזמנה') and p_row['מינימום להזמנה'] != "" else target
                        except: stock, target, min_val = 0.0, 0.0, 0.0
                        
                        if stock <= min_val:
                            diff = max(0.0, target - stock)
                            try: factor = float(p_row['מקדם המרה']) if p_row['מקדם המרה'] != "" else 1.0
                            except: factor = 1.0
                            
                            # חישוב המלצה עם עיגול אוטומטי למעלה
                            rec = math.ceil(diff * factor)
                        else: rec = 0
                        
                        col1, col2 = st.columns([3, 1])
                        status_color = "🔴" if stock <= min_val else "🟢"
                        col1.write(f"{status_color} **{p_name}** (מלאי: {int(stock)})")
                        
                        # גם כאן - הזמנה היא רק במספרים שלמים
                        final_q = col2.number_input(f"להזמין", min_value=0, step=1, value=int(rec), key=f"f_{idx}_{p_name}")
                        
                        if final_q > 0:
                            order_lines.append(f"• {p_name}: {int(final_q)} {p_row['יחידת הזמנה']}")
                    
                    if st.form_submit_button(f"אשר הזמנה ({s})"):
                        msg = f"הזמנה ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                        arch_ws.append_row([datetime.now().strftime("%d/%m/%Y"), s, msg])
                        tasks_ws.delete_rows(idx + 2)
                        st.session_state[f"msg_{s}"] = msg
                        st.rerun()

                if f"msg_{s}" in st.session_state:
                    st.text_area("הודעה להעתקה:", st.session_state[f"msg_{s}"], height=200)

# --- ארכיון ועריכה ---
elif choice == "ארכיון":
    st.header("📜 היסטוריה")
    data = arch_ws.get_all_records()
    if data: st.dataframe(pd.DataFrame(data).iloc[::-1], use_container_width=True)

elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכה")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    edited = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    if st.button("שמור"):
        inv_ws.update([edited.columns.values.tolist()] + edited.values.tolist(), value_input_option='RAW')
        st.success("עודכן!")
