import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

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
except Exception as e:
    st.error(f"חיבור נכשל: {e}")
    st.stop()

is_admin = st.query_params.get("role") == "admin"
st.title("🍕 מערכת ניהול פיצטה")

menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"] if is_admin else ["המשימות שלי"]
choice = st.sidebar.selectbox("תפריט", menu)

# --- 1. מנהל: הקצאת משימות ---
if choice == "ניהול משימות":
    st.header("🎯 שליחת ספקים לספירה")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    all_suppliers = sorted(df_inv['ספק'].unique())
    selected = st.multiselect("בחר ספקים לספירה היום:", all_suppliers)
    
    if st.button("שלח משימות לעובדים ✅"):
        if selected:
            for s in selected:
                tasks_ws.append_row([s, "לביצוע ⏳", datetime.now().strftime("%d/%m %H:%M"), ""])
            st.success(f"נשלחו {len(selected)} משימות!")
        else:
            st.warning("נא לבחור ספק.")

# --- 2. עובד: ביצוע משימות (הקלדה ללא רענון + עדכון טבלה מרכזית) ---
elif choice == "המשימות שלי":
    st.header("📋 משימות פתוחות")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    if 'סטטוס' in df_tasks.columns:
        pending = df_tasks[df_tasks['סטטוס'] == "לביצוע ⏳"]
        if pending.empty:
            st.info("הכל נקי! אין משימות פתוחות.")
        else:
            df_inv = pd.DataFrame(inv_ws.get_all_records())
            for idx, t_row in pending.iterrows():
                with st.expander(f"ספירת מלאי: {t_row['ספק']}", expanded=True):
                    s_prods = df_inv[df_inv['ספק'] == t_row['ספק']]
                    
                    # שימוש בטופס למניעת רענון קופץ
                    with st.form(key=f"form_{idx}"):
                        current_updates = {}
                        for _, p_row in s_prods.iterrows():
                            p_name = p_row['מוצר']
                            st.write(f"**{p_name}** ({p_row['יחידת מידה']})")
                            
                            # שדה הקלדה נוח למובייל
                            val = st.number_input("כמות במלאי:", min_value=0.0, step=0.5, key=f"in_{idx}_{p_name}")
                            
                            # שומרים את האינדקס של השורה בגיליון ה-Inventory (אינדקס + 2)
                            inv_row_idx = df_inv[df_inv['מוצר'] == p_name].index[0] + 2
                            current_updates[inv_row_idx] = val
                            st.divider()
                        
                        if st.form_submit_button(f"💾 סיים ושלח ספירת {t_row['ספק']}"):
                            # 1. עדכון סטטוס המשימה בגיליון Tasks
                            tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                            
                            # 2. עדכון המלאי בפועל בגיליון Inventory (עמודה "מלאי בפועל")
                            col_idx = df_inv.columns.get_loc("מלאי בפועל") + 1
                            for r_idx, amount in current_updates.items():
                                inv_ws.update_cell(r_idx, col_idx, amount)
                            
                            st.success(f"ספירת {t_row['ספק']} עודכנה בטבלה הראשית!")
                            st.rerun()

# --- 3. מנהל: אישור והזמנות (קריאה ישירות מהמלאי המעודכן) ---
elif choice == "אישור והזמנות":
    st.header("🛒 יצירת הזמנות")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    ready_tasks = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
    
    if ready_tasks.empty:
        st.warning("אין ספירות שהסתיימו.")
    else:
        df_inv = pd.DataFrame(inv_ws.get_all_records())
        for idx, t_row in ready_tasks.iterrows():
            s_name = t_row['ספק']
            st.subheader(f"בדיקת הזמנה עבור: {s_name}")
            
            s_prods = df_inv[df_inv['ספק'] == s_name]
            order_summary = []
            
            with st.form(key=f"admin_{idx}"):
                for _, p_row in s_prods.iterrows():
                    p_name = p_row['מוצר']
                    stock = float(p_row['מלאי בפועל']) if p_row['מלאי בפועל'] != "" else 0.0
                    try: target = float(p_row['יעד השלמה']) if p_row['יעד השלמה'] != "" else 0.0
                    except: target = 0.0
                    
                    rec = max(0.0, target - stock)
                    col1, col2 = st.columns([3, 1])
                    col1.write(f"**{p_name}** (במלאי: {stock})")
                    final_q = col2.number_input("להזמין:", 0.0, value=float(rec), key=f"ord_{idx}_{p_name}")
                    
                    if final_q > 0:
                        try: factor = float(p_row['מקדם המרה']) if p_row['מקדם המרה'] != "" else 1.0
                        except: factor = 1.0
                        total = final_q * factor
                        order_summary.append(f"• {p_name}: {total} {p_row['יחידת הזמנה']}")
                
                if st.form_submit_button("אשר וסגור משימה"):
                    msg = f"הזמנה ל-{s_name}:\n" + "\n".join(order_summary) + "\nתודה!"
                    st.session_state[f"msg_{idx}"] = msg
                    sh.worksheet("Archive").append_row([datetime.now().strftime("%d/%m/%Y"), s_name, msg])
                    # מחיקת המשימה מהרשימה הפתוחה
                    tasks_ws.delete_rows(idx + 2)
                    st.rerun()
            
            if f"msg_{idx}" in st.session_state:
                st.text_area("הודעה להעתקה:", st.session_state[f"msg_{idx}"], height=120)

# --- ארכיון ועריכה ---
elif choice == "ארכיון":
    st.dataframe(pd.DataFrame(sh.worksheet("Archive").get_all_records()))

elif choice == "עריכת קטלוג":
    df = pd.DataFrame(inv_ws.get_all_records())
    edited = st.data_editor(df, num_rows="dynamic")
    if st.button("שמור"):
        inv_ws.update([edited.columns.values.tolist()] + edited.values.tolist(), value_input_option='RAW')
        st.success("נשמר!")
