import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import ast

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

# פונקציית התחברות מאובטחת
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    return gspread.authorize(creds)

try:
    gc = get_gsheet_client()
    sh = gc.open_by_key("1-f7O8vH9-7ZGqRgZIiINy17YUywErcK332MzuYyNerQ")
except Exception as e:
    st.error(f"שגיאת התחברות: {e}")
    st.stop()

is_admin = st.query_params.get("role") == "admin"
st.title("🍕 מערכת ניהול פיצטה")

if is_admin:
    menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"]
else:
    menu = ["המשימות שלי"]

choice = st.sidebar.selectbox("תפריט ניווט", menu)

# --- 1. מנהל: ניהול משימות ---
if choice == "ניהול משימות":
    st.header("🎯 הקצאת ספקים לספירה")
    inv_ws = sh.worksheet("Inventory")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    all_suppliers = sorted(df_inv['ספק'].unique())
    selected_suppliers = st.multiselect("חפש ובחר ספקים:", all_suppliers)
    
    if st.button("שלח משימות לעובד ✅"):
        if not selected_suppliers:
            st.warning("נא לבחור ספק.")
        else:
            tasks_ws = sh.worksheet("Tasks")
            for s in selected_suppliers:
                tasks_ws.append_row([s, "לביצוע ⏳", datetime.now().strftime("%d/%m %H:%M"), "{}"])
            st.success("המשימות נשלחו!")

# --- 2. עובד: המשימות שלי (ללא רענון אוטומטי קופץ) ---
elif choice == "המשימות שלי":
    st.header("📋 משימות ספירה")
    tasks_ws = sh.worksheet("Tasks")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    if 'סטטוס' in df_tasks.columns:
        pending = df_tasks[df_tasks['סטטוס'] == "לביצוע ⏳"]
        if pending.empty:
            st.info("אין משימות פתוחות.")
        else:
            inv_ws = sh.worksheet("Inventory")
            df_inv = pd.DataFrame(inv_ws.get_all_records())
            
            for idx, row in pending.iterrows():
                with st.expander(f"ספירה עבור: {row['ספק']}", expanded=True):
                    s_prods = df_inv[df_inv['ספק'] == row['ספק']]
                    worker_counts = {}
                    
                    # שימוש בטופס (Form) כדי שכל הלחיצות יקרו "בבת אחת" בסוף
                    with st.form(key=f"worker_form_{idx}"):
                        for _, p_row in s_prods.iterrows():
                            p_name = p_row['מוצר']
                            key = f"count_{idx}_{p_name}"
                            
                            # ערך ברירת מחדל מהקטלוג או 0
                            initial_val = st.session_state.get(key, 0.0)
                            
                            st.write(f"**{p_name}** ({p_row['יחידת מידה']})")
                            
                            # כאן העובד פשוט מקליד או משתמש בחצים המובנים של הדפדפן (יותר יציב במובייל)
                            # זה מונע מהדף לקפוץ בכל לחיצה
                            res = st.number_input("כמות:", min_value=0.0, step=0.5, value=initial_val, key=key)
                            worker_counts[p_name] = res
                            st.divider()
                        
                        # רק בלחיצה על הכפתור הזה הכל נשלח ומתעדכן בגוגל שיטס
                        submit_all = st.form_submit_button(f"🚀 סיימתי הכל - שלח ספירת {row['ספק']}")
                        
                        if submit_all:
                            tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                            tasks_ws.update_cell(idx + 2, 4, str(worker_counts))
                            st.success("הספירה נשלחה בהצלחה!")
                            st.rerun()

# --- 3. מנהל: אישור והזמנות ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור הזמנות")
    tasks_ws = sh.worksheet("Tasks")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    if 'סטטוס' in df_tasks.columns:
        ready = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
        if ready.empty:
            st.warning("אין ספירות ממתינות.")
        else:
            inv_ws = sh.worksheet("Inventory")
            df_inv = pd.DataFrame(inv_ws.get_all_records())
            
            for idx, t_row in ready.iterrows():
                s = t_row['ספק']
                st.subheader(f"בדיקה: {s}")
                
                raw_counts = t_row.get('נתוני_ספירה', "{}")
                try: counts = ast.literal_eval(raw_counts)
                except: counts = {}
                
                order_lines = []
                s_prods = df_inv[df_inv['ספק'] == s]
                
                with st.form(key=f"admin_form_{idx}"):
                    for _, row in s_prods.iterrows():
                        p = row['מוצר']
                        stock = float(counts.get(p, 0.0))
                        try: target_val = float(row['יעד השלמה']) if row['יעד השלמה'] != "" else 0.0
                        except: target_val = 0.0
                        rec = max(0.0, target_val - stock)
                        
                        col_p, col_q = st.columns([3, 1])
                        col_p.write(f"**{p}** (במלאי: {stock})")
                        final_q = col_q.number_input(f"להזמין", 0.0, value=float(rec), key=f"f_{idx}_{p}")
                        
                        if final_q > 0:
                            try: factor = float(row['מקדם המרה']) if row['מקדם המרה'] != "" else 1.0
                            except: factor = 1.0
                            total = final_q * factor
                            display_q = int(total) if total.is_integer() else total
                            order_lines.append(f"• {p}: {display_q} {row['יחידת הזמנה']}")
                    
                    if st.form_submit_button(f"ייצר הודעה וסגור משימה ({s})"):
                        msg = f"היי, כאן מפיצטה.\nנשמח להזמין ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                        st.session_state[f"final_msg_{idx}"] = msg
                        sh.worksheet("Archive").append_row([datetime.now().strftime("%d/%m/%Y"), s, msg])
                        tasks_ws.delete_rows(idx + 2)
                        st.rerun()

                if f"final_msg_{idx}" in st.session_state:
                    st.text_area("הודעה מוכנה:", st.session_state[f"final_msg_{idx}"], height=150)

# --- ארכיון ועריכת קטלוג ---
elif choice == "ארכיון":
    st.header("📜 היסטוריה")
    df_arch = pd.DataFrame(sh.worksheet("Archive").get_all_records())
    st.dataframe(df_arch, use_container_width=True)

elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכה")
    inv_ws = sh.worksheet("Inventory")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    edited = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    if st.button("שמור"):
        inv_ws.update([edited.columns.values.tolist()] + edited.values.tolist(), value_input_option='RAW')
        st.success("עודכן!")
