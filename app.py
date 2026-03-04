import streamlit as st
import pandas as pd
from datetime import datetime
import io
import requests

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

# כתובת הגיליון שלך
SHEET_ID = "1-f7O8vH9-7ZGqRgZIiINy17YUywErcK332MzuYyNerQ"
BASE_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"

# פונקציות טעינה (קריאה ישירה כ-CSV למניעת שגיאות HTTP)
def load_sheet(sheet_name):
    url = f"{BASE_URL}&sheet={sheet_name}"
    response = requests.get(url)
    return pd.read_csv(io.StringIO(response.text))

# זיהוי תפקיד לפי URL: ?role=admin
is_admin = st.query_params.get("role") == "admin"

st.title("🍕 מערכת ניהול פיצטה")

if is_admin:
    st.sidebar.success("🔓 מצב מנהל")
    menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"]
else:
    st.sidebar.info("👤 מצב עובד")
    menu = ["המשימות שלי"]

choice = st.sidebar.selectbox("תפריט", menu)

# --- לוגיקה לעובד ---
if choice == "המשימות שלי":
    st.header("📋 משימות ספירה פתוחות")
    try:
        tasks_df = load_sheet("Tasks")
        # ניקוי עמודות ריקות אם יש
        tasks_df = tasks_df.dropna(how='all', axis=1).dropna(how='all', axis=0)
        
        pending = tasks_df[tasks_df['סטטוס'] == "לביצוע ⏳"]
        
        if pending.empty:
            st.info("אין משימות פתוחות כרגע.")
        else:
            for idx, row in pending.iterrows():
                with st.expander(f"ספירה עבור: {row['ספק']}", expanded=True):
                    st.warning("שים לב: בסיום הספירה עליך לעדכן את המנהל (האפליקציה בגרסת קריאה)")
                    # תצוגת מוצרים לספירה
                    inv_df = load_sheet("Inventory")
                    s_prods = inv_df[inv_df['ספק'] == row['ספק']]
                    for _, p_row in s_prods.iterrows():
                        st.number_input(f"{p_row['מוצר']} ({p_row['יחידת מידה']})", 0.0, step=0.1, key=f"{idx}_{p_row['מוצר']}")
                    st.button("שלח ספירה (בפיתוח)", key=f"btn_{idx}")
    except Exception as e:
        st.error(f"שגיאה בטעינת משימות: {e}")

# --- לוגיקה למנהל: אישור והזמנה ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור והמרת כמויות")
    # כאן המערכת תבצע את החישובים של מקדם המרה (למשל 8 לעגבניות)
    st.info("בחר משימה שבוצעה כדי לייצר הודעה")
    # (המשך הלוגיקה של ההמרות שהגדרנו קודם)

# --- עריכת קטלוג ---
elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכת נתוני סחורה")
    df_inv = load_sheet("Inventory")
    st.data_editor(df_inv, use_container_width=True)
    st.link_button("פתח גיליון גוגל לעריכה ישירה", f"https://docs.google.com/spreadsheets/d/{SHEET_ID}")
