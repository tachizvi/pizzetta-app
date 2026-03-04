import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

# החלף את הכתובת למטה בקישור המלא של הגוגל שיטס שלך
url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID_HERE/edit#gid=0"
conn = st.connection("gsheets", type=GSheetsConnection)

# פונקציות עזר מעודכנות שמשתמשות ב-URL ישירות
def get_inventory():
    return conn.read(spreadsheet=url, worksheet="Inventory", ttl="1m")

def get_tasks():
    return conn.read(spreadsheet=url, worksheet="Tasks", ttl="0")

def get_archive():
    return conn.read(spreadsheet=url, worksheet="Archive", ttl="1m")


# זיהוי תפקיד לפי URL (למשל: ?role=admin)
is_admin = st.query_params.get("role") == "admin"

st.title("🍕 מערכת ניהול פיצטה")

if is_admin:
    st.sidebar.success("🔓 מחובר כמנהל")
    menu = ["ניהול משימות", "אישור והזמנות", "ארכיון הזמנות", "עריכת קטלוג"]
else:
    st.sidebar.info("👤 מחובר כעובד")
    menu = ["המשימות שלי"]

choice = st.sidebar.selectbox("תפריט ניווט", menu)

# --- 1. מנהל: הקצאת משימות ---
if choice == "ניהול משימות":
    st.header("🎯 הקצאת ספקים לספירה")
    df_inv = get_inventory()
    suppliers = sorted(df_inv['ספק'].unique())
    selected = st.multiselect("בחר ספקים שהעובד צריך לספור כעת:", suppliers)
    
    if st.button("שלח משימות לעובד"):
        tasks_df = get_tasks()
        # יצירת שורות חדשות למשימות
        new_entries = pd.DataFrame([
            {"ספק": s, "סטטוס": "לביצוע ⏳", "נתוני_ספירה": "{}"} 
            for s in selected
        ])
        # עדכון הגליון בענן
        updated_tasks = pd.concat([tasks_df, new_entries], ignore_index=True)
        conn.update(worksheet="Tasks", data=updated_tasks)
        st.success("המשימות נשלחו בהצלחה ויופיעו אצל העובד!")

# --- 2. עובד: ביצוע ספירה ---
elif choice == "המשימות שלי":
    st.header("📋 משימות ספירה פתוחות")
    tasks_df = get_tasks()
    pending = tasks_df[tasks_df['סטטוס'] == "לביצוע ⏳"]
    
    if pending.empty:
        st.info("אין משימות פתוחות כרגע. ברגע שהמנהל יקצה משימה, היא תופיע כאן.")
    else:
        for idx, row_task in pending.iterrows():
            s = row_task['ספק']
            with st.expander(f"ספירה עבור: {s}", expanded=True):
                with st.form(key=f"form_{idx}"):
                    counts = {}
                    inv_df = get_inventory()
                    s_prods = inv_df[inv_df['ספק'] == s]
                    for _, row in s_prods.iterrows():
                        counts[row['מוצר']] = st.number_input(
                            f"{row['מוצר']} ({row['יחידת מידה']})", 
                            min_value=0.0, step=0.1
                        )
                    
                    if st.form_submit_button("סיים ספירה ושלח"):
                        tasks_df.at[idx, 'סטטוס'] = "ממתין לאישור 🟡"
                        tasks_df.at[idx, 'נתוני_ספירה'] = str(counts)
                        conn.update(worksheet="Tasks", data=tasks_df)
                        st.success(f"הספירה של {s} נשלחה!")
                        st.rerun()

# --- 3. מנהל: אישור והזמנה חכמה ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור הזמנות סופי")
    tasks_df = get_tasks()
    ready = tasks_df[tasks_df['סטטוס'] == "ממתין לאישור 🟡"]
    
    if ready.empty:
        st.warning("אין ספירות שממתינות לאישור המנהל.")
    else:
        inv_df = get_inventory()
        for idx, row_task in ready.iterrows():
            s = row_task['ספק']
            st.subheader(f"בדיקת כמויות: {s}")
            # המרת המחרוזת חזרה למילון פייתון
            try:
                counts = eval(row_task['נתוני_ספירה'])
            except:
                counts = {}
            
            order_lines = []
            s_prods = inv_df[inv_df['ספק'] == s]
            
            for _, row in s_prods.iterrows():
                p = row['מוצר']
                stock = counts.get(p, 0.0)
                target = row['יעד השלמה']
                
                # המלצת השלמה אוטומטית (ביחידת ספירה)
                rec = max(0.0, float(target) - stock) if pd.notnull(target) and target != "" else 0.0
                
                col1, col2, col3 = st.columns([2, 1, 1])
                col1.write(f"**{p}** (במלאי: {stock} {row['יחידת מידה']})")
                final_q = col3.number_input(f"להזמין ({row['יחידת מידה']})", 0.0, value=float(rec), key=f"q_{idx}_{p}")
                
                if final_q > 0:
                    # חישוב המרה ליחידת ספק
                    factor = float(row['מקדם המרה']) if pd.notnull(row['מקדם המרה']) else 1.0
                    total = final_q * factor
                    display_q = int(total) if total.is_integer() else round(total, 2)
                    order_lines.append(f"• {p}: {display_q} {row['יחידת הזמנה']}")
            
            if st.button(f"ייצר הודעה וסגור משימה ({s})", key=f"btn_{idx}"):
                full_msg = f"היי, כאן מפיצטה.\nנשמח להזמין ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                st.session_state[f"msg_{idx}"] = full_msg
                
                # העברה לארכיון ומחיקה מהמשימות
                archive_df = get_archive()
                new_archive = pd.DataFrame([{"תאריך": datetime.now().strftime("%d/%m/%Y %H:%M"), "ספק": s, "פירוט_הזמנה": full_msg}])
                conn.update(worksheet="Archive", data=pd.concat([archive_df, new_archive], ignore_index=True))
                
                tasks_df.drop(idx, inplace=True)
                conn.update(worksheet="Tasks", data=tasks_df)
                st.rerun()

            if f"msg_{idx}" in st.session_state:
                st.info("ההודעה מוכנה להעתקה:")
                st.text_area("העתק מכאן:", st.session_state[f"msg_{idx}"], height=150)

# --- 4. מנהל: ארכיון ועריכה ---
elif choice == "ארכיון הזמנות":
    st.header("📜 היסטוריית הזמנות")
    st.dataframe(get_archive(), use_container_width=True)

elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכת קובץ המלאי")
    df_inv = get_inventory()
    edited_df = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    if st.button("שמור שינויים בענן"):
        conn.update(worksheet="Inventory", data=edited_df)

        st.success("הקטלוג עודכן בהצלחה!")
