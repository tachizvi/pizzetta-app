import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

# פונקציית התחברות מאובטחת באמצעות ה-Secrets שהגדרת
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    return gspread.authorize(creds)

# אתחול חיבור
try:
    gc = get_gsheet_client()
    # המזהה של הגיליון שלך
    sh = gc.open_by_key("1-f7O8vH9-7ZGqRgZIiINy17YUywErcK332MzuYyNerQ")
except Exception as e:
    st.error(f"שגיאת התחברות: {e}")
    st.info("וודא שה-Secrets בפורמט TOML ושהמייל של הבוט הוגדר כ-Editor בגליון.")
    st.stop()

# זיהוי תפקיד לפי URL: ?role=admin
is_admin = st.query_params.get("role") == "admin"

st.title("🍕 מערכת ניהול פיצטה")

if is_admin:
    st.sidebar.success("🔓 מחובר כמנהל")
    menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"]
else:
    st.sidebar.info("👤 מחובר כעובד")
    menu = ["המשימות שלי"]

choice = st.sidebar.selectbox("תפריט ניווט", menu)

# --- 1. מנהל: ניהול משימות (הוספת משימות) ---
if choice == "ניהול משימות":
    st.header("🎯 הקצאת ספקים לספירה")
    
    # טעינת קטלוג ספקים מהלשונית Inventory
    inv_ws = sh.worksheet("Inventory")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    all_suppliers = sorted(df_inv['ספק'].unique())
    
    # תיבת החיפוש והבחירה המרובה
    selected_suppliers = st.multiselect("חפש ובחר ספקים לספירה:", all_suppliers)
    
    if st.button("שלח משימות לעובד ✅"):
        if not selected_suppliers:
            st.warning("נא לבחור לפחות ספק אחד.")
        else:
            tasks_ws = sh.worksheet("Tasks")
            for s in selected_suppliers:
                # כתיבת שורה חדשה לגוגל שיטס
                tasks_ws.append_row([
                    s, 
                    "לביצוע ⏳", 
                    datetime.now().strftime("%d/%m %H:%M"), 
                    "{}" # מקום לנתוני הספירה העתידיים
                ])
            st.success(f"נשלחו {len(selected_suppliers)} משימות. העובד יראה אותן מיד בטלפון!")

# --- 2. עובד: המשימות שלי (ביצוע ספירה) ---
elif choice == "המשימות שלי":
    st.header("📋 משימות ספירה פתוחות")
    tasks_ws = sh.worksheet("Tasks")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    # סינון משימות שטרם בוצעו
    pending = df_tasks[df_tasks['סטטוס'] == "לביצוע ⏳"]
    
    if pending.empty:
        st.info("אין משימות פתוחות כרגע. עבודה טובה!")
    else:
        inv_ws = sh.worksheet("Inventory")
        df_inv = pd.DataFrame(inv_ws.get_all_records())
        
        for idx, row in pending.iterrows():
            with st.expander(f"ספירה עבור: {row['ספק']}", expanded=True):
                s_prods = df_inv[df_inv['ספק'] == row['ספק']]
                worker_counts = {}
                
                with st.form(key=f"form_{idx}"):
                    for _, p_row in s_prods.iterrows():
                        worker_counts[p_row['מוצר']] = st.number_input(
                            f"{p_row['מוצר']} ({p_row['יחידת מידה']})", 
                            min_value=0.0, step=0.1
                        )
                    
                    if st.form_submit_button("סיים ספירה ושלח למנהל"):
                        # עדכון סטטוס ונתונים בגיליון (שורה idx+2 בגלל כותרת ואינדקס 0)
                        tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                        tasks_ws.update_cell(idx + 2, 4, str(worker_counts))
                        st.success("הספירה נשמרה בהצלחה!")
                        st.rerun()

# --- 3. מנהל: אישור והזמנות (המרות יחידות) ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור הזמנות וייצור הודעה")
    tasks_ws = sh.worksheet("Tasks")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    ready = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
    
    if ready.empty:
        st.warning("אין ספירות שהסתיימו וממתינות לאישור.")
    else:
        inv_ws = sh.worksheet("Inventory")
        df_inv = pd.DataFrame(inv_ws.get_all_records())
        
        for idx, t_row in ready.iterrows():
            s = t_row['ספק']
            st.subheader(f"בדיקת הזמנה לספק: {s}")
            
            try:
                counts = eval(t_row['נתוני_ספירה'])
            except:
                counts = {}
                
            order_lines = []
            s_prods = df_inv[df_inv['ספק'] == s]
            
            for _, row in s_prods.iterrows():
                p = row['מוצר']
                stock = counts.get(p, 0.0)
                target = row['יעד השלמה']
                rec = max(0.0, float(target) - stock) if pd.notnull(target) else 0.0
                
                col1, col2, col3 = st.columns([2, 1, 1])
                col1.write(f"**{p}** (מלאי: {stock})")
                final_q = col3.number_input(f"להזמין ({row['יחידת מידה']})", 0.0, value=float(rec), key=f"q_{idx}_{p}")
                
                if final_q > 0:
                    # לוגיקת המרה: למשל 2 קופסאות * 8 קילו = 16 קילו
                    factor = float(row['מקדם המרה']) if pd.notnull(row['מקדם המרה']) else 1.0
                    total = final_q * factor
                    display_q = int(total) if total.is_integer() else total
                    order_lines.append(f"• {p}: {display_q} {row['יחידת הזמנה']}")
            
            if st.button(f"ייצר הודעה וסגור משימה ({s})", key=f"btn_{idx}"):
                full_msg = f"היי, כאן מפיצטה.\nנשמח להזמין ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                st.text_area("הודעה להעתקה:", full_msg, height=150)
                
                # העברה לארכיון ומחיקה מהמשימות הפעילות
                arch_ws = sh.worksheet("Archive")
                arch_ws.append_row([datetime.now().strftime("%d/%m/%Y"), s, full_msg])
                tasks_ws.delete_rows(idx + 2)
                st.rerun()

# --- 4. מנהל: עריכת קטלוג ---
elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכת נתוני מוצרים")
    inv_ws = sh.worksheet("Inventory")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    edited_df = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    
    if st.button("שמור שינויים בקטלוג"):
        inv_ws.update([edited_df.columns.values.tolist()] + edited_df.values.tolist())
        st.success("הקטלוג עודכן בענן!")
