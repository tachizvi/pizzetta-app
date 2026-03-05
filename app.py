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

# --- 2. עובד: המשימות שלי ---
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
                            val = st.number_input("כמות במלאי (שלם):", min_value=0, step=1, value=0, key=f"in_{idx}_{p_name}")
                            inv_row_idx = df_inv[df_inv['מוצר'] == p_name].index[0] + 2
                            current_updates[inv_row_idx] = val
                        if st.form_submit_button(f"💾 שלח ספירת {t_row['ספק']}"):
                            tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                            col_idx = full_data[0].index("מלאי בפועל") + 1
                            updates = [{'range': gspread.utils.rowcol_to_a1(r, col_idx), 'values': [[v]]} for r, v in current_updates.items()]
                            inv_ws.batch_update(updates)
                            st.success("עודכן!")
                            st.rerun()

# --- 3. מנהל: אישור והזמנות (עם עיגול סופי ליחידות ספק) ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור והזמנות (ביחידות ספירה)")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    if 'סטטוס' in df_tasks.columns:
        ready = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
        if not ready.empty:
            df_inv = pd.DataFrame(inv_ws.get_all_records())
            for idx, t_row in ready.iterrows():
                s = t_row['ספק']
                st.subheader(f"בדיקה: {s}")
                s_prods = df_inv[df_inv['ספק'] == s]
                
                with st.form(key=f"admin_form_{idx}"):
                    final_orders = {}
                    valid_to_order = True
                    
                    for _, p_row in s_prods.iterrows():
                        p_name = p_row['מוצר']
                        try:
                            stock = int(p_row['מלאי בפועל']) if p_row['מלאי בפועל'] != "" else 0
                            target = int(p_row['יעד השלמה']) if p_row['יעד השלמה'] != "" else 0
                            min_val = int(p_row['מינימום להזמנה']) if p_row.get('מינימום להזמנה') and p_row['מינימום להזמנה'] != "" else target
                            mult = int(p_row['כפולת הזמנה']) if p_row.get('כפולת הזמנה') and p_row['כפולת הזמנה'] != "" else 1
                        except: stock, target, min_val, mult = 0, 0, 0, 1
                        
                        # המלצה ראשונית (ביחידות ספירה)
                        rec = max(0, target - stock) if stock <= min_val else 0
                        # עיגול אוטומטי לכפולה הקרובה ביותר מלמעלה
                        if rec > 0 and rec % mult != 0:
                            rec = math.ceil(rec / mult) * mult
                            
                        col1, col2 = st.columns([3, 1])
                        status_color = "🔴" if stock <= min_val else "🟢"
                        col1.write(f"{status_color} **{p_name}** (מלאי: {stock} {p_row['יחידת מידה']})")
                        
                        order_val = col2.number_input(f"להזמין ({p_row['יחידת מידה']})", min_value=0, step=1, value=rec, key=f"f_{idx}_{p_name}")
                        
                        # בדיקת כפולות
                        if order_val > 0 and order_val % mult != 0:
                            st.error(f"שגיאה: {p_name} חייב להיות בכפולות של {mult}!")
                            valid_to_order = False
                        
                        if order_val > 0:
                            try: factor = float(p_row['מקדם המרה']) if p_row['מקדם המרה'] != "" else 1.0
                            except: factor = 1.0
                            
                            # כאן העיגול הסופי! 
                            # אנחנו משתמשים ב-round(..., 2) כדי לפתור בעיות של 0.99999 
                            # ואז math.ceil כדי להבטיח יחידת ספק שלמה.
                            raw_qty = order_val * factor
                            final_qty = math.ceil(round(raw_qty, 4))
                            
                            final_orders[p_name] = {"qty": int(final_qty), "unit": p_row['יחידת הזמנה']}

                    if st.form_submit_button(f"אשר ושגר הזמנה ({s})"):
                        if valid_to_order and final_orders:
                            order_lines = [f"• {name}: {data['qty']} {data['unit']}" for name, data in final_orders.items()]
                            msg = f"הזמנה ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                            arch_ws.append_row([datetime.now().strftime("%d/%m/%Y"), s, msg])
                            tasks_ws.delete_rows(idx + 2)
                            st.session_state[f"msg_{s}"] = msg
                            st.rerun()

                if f"msg_{s}" in st.session_state:
                    st.text_area("הודעה להעתקה:", st.session_state[f"msg_{s}"], height=200)
                    if st.button(f"סגור הודעה ({s})"):
                        del st.session_state[f"msg_{s}"]
                        st.rerun()

# --- ארכיון ועריכה ---
elif choice == "ארכיון":
    st.header("📜 היסטוריה")
    data = arch_ws.get_all_records()
    if data: st.dataframe(pd.DataFrame(data).iloc[::-1], use_container_width=True)

elif choice == "עריכת קטלוג":
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    edited = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    if st.button("שמור"):
        inv_ws.update([edited.columns.values.tolist()] + edited.values.tolist(), value_input_option='RAW')
        st.success("עודכן!")
