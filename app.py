import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import math

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

# פונקציית התחברות מאובטחת
@st.cache_resource
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    return gspread.authorize(creds)

try:
    gc = get_gsheet_client()
    # המזהה של הגיליון שלך
    sh = gc.open_by_key("1-f7O8vH9-7ZGqRgZIiINy17YUywErcK332MzuYyNerQ")
    inv_ws = sh.worksheet("Inventory")
    tasks_ws = sh.worksheet("Tasks")
    arch_ws = sh.worksheet("Archive")
except Exception as e:
    st.error(f"חיבור נכשל: {e}")
    st.stop()

# זיהוי תפקיד לפי URL: ?role=admin
is_admin = st.query_params.get("role") == "admin"

st.title("🍕 מערכת ניהול פיצטה")

if is_admin:
    menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"]
else:
    menu = ["המשימות שלי"]

choice = st.sidebar.selectbox("תפריט ניווט", menu)

# --- 1. מנהל: ניהול משימות ---
if choice == "ניהול משימות":
    st.header("🎯 שליחת ספקים לספירה")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    all_suppliers = sorted(df_inv['ספק'].unique())
    selected = st.multiselect("בחר ספקים לספירה היום:", all_suppliers)
    
    if st.button("שלח משימות לעובד ✅"):
        if selected:
            for s in selected:
                tasks_ws.append_row([s, "לביצוע ⏳", datetime.now().strftime("%d/%m %H:%M"), ""])
            st.success(f"נשלחו {len(selected)} משימות!")
        else:
            st.warning("נא לבחור ספק.")

# --- 2. עובד: המשימות שלי (ספירה ללא רענון קופץ) ---
elif choice == "המשימות שלי":
    st.header("📋 משימות פתוחות")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    if 'סטטוס' in df_tasks.columns:
        pending = df_tasks[df_tasks['סטטוס'] == "לביצוע ⏳"]
        if pending.empty:
            st.info("אין משימות פתוחות כרגע.")
        else:
            # טעינת נתוני אינוונטרי פעם אחת (Batch Read)
            full_data = inv_ws.get_all_values()
            df_inv = pd.DataFrame(full_data[1:], columns=full_data[0])
            
            for idx, t_row in pending.iterrows():
                with st.expander(f"ספירה עבור: {t_row['ספק']}", expanded=True):
                    s_prods = df_inv[df_inv['ספק'] == t_row['ספק']]
                    
                    with st.form(key=f"worker_form_{idx}"):
                        current_updates = {}
                        for _, p_row in s_prods.iterrows():
                            p_name = p_row['מוצר']
                            st.write(f"**{p_name}** ({p_row['יחידת מידה']})")
                            
                            # שדה הקלדה נוח
                            val = st.number_input("כמות במלאי:", min_value=0.0, step=0.5, key=f"in_{idx}_{p_name}")
                            
                            # שמירת המיקום בטבלה
                            inv_row_idx = df_inv[df_inv['מוצר'] == p_name].index[0] + 2
                            current_updates[inv_row_idx] = val
                            st.divider()
                        
                        if st.form_submit_button(f"💾 סיים ושלח ספירת {t_row['ספק']}"):
                            # עדכון סטטוס משימה
                            tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                            
                            # עדכון מלאי בפועל ב-Batch (מניעת Quota Exceeded)
                            col_idx = full_data[0].index("מלאי בפועל") + 1
                            updates = []
                            for r_idx, amount in current_updates.items():
                                updates.append({
                                    'range': gspread.utils.rowcol_to_a1(r_idx, col_idx),
                                    'values': [[amount]]
                                })
                            inv_ws.batch_update(updates)
                            
                            st.success(f"הספירה עודכנה!")
                            st.rerun()

# --- 3. מנהל: אישור והזמנות (עם לוגיקת מינימום ועיגול) ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור והמרת כמויות להזמנה")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    if 'סטטוס' in df_tasks.columns:
        ready = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
        if ready.empty:
            st.warning("אין ספירות שממתינות לאישור.")
        else:
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
                        
                        # לוגיקת החישוב
                        if stock <= min_val:
                            rec = max(0.0, target - stock)
                            # בדיקת עיגול למעלה
                            if p_row.get('עיגול ליחידה שלמה') and str(p_row['עיגול ליחידה שלמה']).strip() == "כן":
                                rec = math.ceil(rec)
                        else:
                            rec = 0.0
                            
                        col1, col2 = st.columns([3, 1])
                        status_color = "🔴" if stock < min_val else "🟢"
                        col1.write(f"{status_color} **{p_name}** (במלאי: {stock} / מינימום: {min_val})")
                        final_q = col2.number_input(f"להזמין", 0.0, value=float(rec), key=f"f_{idx}_{p_name}")
                        
                        if final_q > 0:
                            try: factor = float(p_row['מקדם המרה']) if p_row['מקדם המרה'] != "" else 1.0
                            except: factor = 1.0
                            total = final_q * factor
                            display_q = int(total) if total.is_integer() else round(total, 2)
                            order_lines.append(f"• {p_name}: {display_q} {p_row['יחידת הזמנה']}")
                    
                    if st.form_submit_button(f"ייצר הודעה וסגור משימה ({s})"):
                        full_msg = f"היי, כאן מפיצטה.\nנשמח להזמין ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                        arch_ws.append_row([datetime.now().strftime("%d/%m/%Y"), s, full_msg])
                        tasks_ws.delete_rows(idx + 2)
                        st.session_state[f"msg_{s}"] = full_msg
                        st.rerun()

                if f"msg_{s}" in st.session_state:
                    st.success(f"ההזמנה ל-{s} נסגרה!")
                    st.text_area("הודעה להעתקה:", st.session_state[f"msg_{s}"], height=200)
                    if st.button(f"סגור חלון ({s})"):
                        del st.session_state[f"msg_{s}"]
                        st.rerun()

# --- 4. ארכיון ועריכה ---
elif choice == "ארכיון":
    st.header("📜 היסטוריית הזמנות")
    data = arch_ws.get_all_records()
    if data:
        st.dataframe(pd.DataFrame(data).iloc[::-1], use_container_width=True)
    else: st.info("ריק.")

elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכת נתוני מוצרים")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    edited = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    if st.button("שמור שינויים"):
        inv_ws.update([edited.columns.values.tolist()] + edited.values.tolist(), value_input_option='RAW')
        st.success("עודכן!")

