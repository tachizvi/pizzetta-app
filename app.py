import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import ast  # ספרייה בטוחה להמרת טקסט למילון

# הגדרות דף
st.set_page_config(page_title="פיצטה - ניהול חכם", page_icon="🍕", layout="wide")

# פונקציית התחברות מאובטחת
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_info = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    return gspread.authorize(creds)

# אתחול חיבור
try:
    gc = get_gsheet_client()
    sh = gc.open_by_key("1-f7O8vH9-7ZGqRgZIiINy17YUywErcK332MzuYyNerQ")
except Exception as e:
    st.error(f"שגיאת התחברות: {e}")
    st.stop()

is_admin = st.query_params.get("role") == "admin"
st.title("🍕 מערכת ניהול פיצטה")

if is_admin:
    st.sidebar.success("🔓 מחובר כמנהל")
    menu = ["ניהול משימות", "אישור והזמנות", "ארכיון", "עריכת קטלוג"]
else:
    st.sidebar.info("👤 מחובר כעובד")
    menu = ["המשימות שלי"]

choice = st.sidebar.selectbox("תפריט ניווט", menu)

# --- 1. מנהל: ניהול משימות ---
if choice == "ניהול משימות":
    st.header("🎯 הקצאת ספקים לספירה")
    inv_ws = sh.worksheet("Inventory")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    all_suppliers = sorted(df_inv['ספק'].unique())
    selected_suppliers = st.multiselect("חפש ובחר ספקים לספירה:", all_suppliers)
    
    if st.button("שלח משימות לעובד ✅"):
        if not selected_suppliers:
            st.warning("נא לבחור לפחות ספק אחד.")
        else:
            tasks_ws = sh.worksheet("Tasks")
            for s in selected_suppliers:
                tasks_ws.append_row([s, "לביצוע ⏳", datetime.now().strftime("%d/%m %H:%M"), "{}"])
            st.success("המשימות נשלחו!")

# --- 2. עובד: המשימות שלי ---
elif choice == "המשימות שלי":
    st.header("📋 משימות ספירה פתוחות")
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
                    for _, p_row in s_prods.iterrows():
                        p_name = p_row['מוצר']
                        key = f"count_{idx}_{p_name}"
                        if key not in st.session_state: st.session_state[key] = 0.0
                        
                        st.write(f"**{p_name}** ({p_row['יחידת מידה']})")
                        col_val, col_p_half, col_p_one, col_minus, col_reset = st.columns([1.5, 1, 1, 1, 1])
                        with col_val: st.metric(label="כמות", value=st.session_state[key])
                        with col_p_half: 
                            if st.button("+0.5", key=f"h_{key}"): 
                                st.session_state[key] += 0.5
                                st.rerun()
                        with col_p_one:
                            if st.button("+1", key=f"o_{key}"):
                                st.session_state[key] += 1.0
                                st.rerun()
                        with col_minus:
                            if st.button("-1", key=f"m_{key}"):
                                st.session_state[key] = max(0.0, st.session_state[key] - 1.0)
                                st.rerun()
                        with col_reset:
                            if st.button("🔄", key=f"r_{key}"):
                                st.session_state[key] = 0.0
                                st.rerun()
                        worker_counts[p_name] = st.session_state[key]
                    
                    if st.button(f"✅ סיים ספירת {row['ספק']}", key=f"sub_{idx}"):
                        tasks_ws.update_cell(idx + 2, 2, "בוצע ✅")
                        tasks_ws.update_cell(idx + 2, 4, str(worker_counts))
                        for k in list(st.session_state.keys()):
                            if k.startswith(f"count_{idx}_"): del st.session_state[k]
                        st.success("נשלח!")
                        st.rerun()

# --- 3. מנהל: אישור והזמנות (תיקון שליפת הנתונים כאן) ---
elif choice == "אישור והזמנות":
    st.header("🛒 אישור והמרת כמויות להזמנה")
    tasks_ws = sh.worksheet("Tasks")
    df_tasks = pd.DataFrame(tasks_ws.get_all_records())
    
    if 'סטטוס' in df_tasks.columns:
        ready = df_tasks[df_tasks['סטטוס'] == "בוצע ✅"]
        if ready.empty:
            st.warning("אין ספירות שממתינות לאישור.")
        else:
            inv_ws = sh.worksheet("Inventory")
            df_inv = pd.DataFrame(inv_ws.get_all_records())
            
            for idx, t_row in ready.iterrows():
                s = t_row['ספק']
                st.subheader(f"בדיקת הזמנה: {s}")
                
                # שליפה בטוחה של נתוני הספירה
                raw_counts = t_row.get('נתוני_ספירה', "{}")
                try:
                    # שימוש ב-ast.literal_eval להמרה בטוחה מטקסט למילון פייתון
                    counts = ast.literal_eval(raw_counts) if isinstance(raw_counts, str) else {}
                except:
                    counts = {}
                
                order_lines = []
                s_prods = df_inv[df_inv['ספק'] == s]
                for _, row in s_prods.iterrows():
                    p = row['מוצר']
                    # וידוא שהערך נשלף כמספר
                    stock = float(counts.get(p, 0.0))
                    
                    try:
                        target_val = float(row['יעד השלמה']) if row['יעד השלמה'] != "" else 0.0
                    except:
                        target_val = 0.0
                        
                    rec = max(0.0, target_val - stock)
                    
                    col1, col2 = st.columns([3, 1])
                    col1.write(f"**{p}** (מלאי שנספר: {stock})")
                    final_q = col2.number_input(f"להזמין ({row['יחידת מידה']})", 0.0, value=float(rec), key=f"f_{idx}_{p}")
                    
                    if final_q > 0:
                        try:
                            factor = float(row['מקדם המרה']) if row['מקדם המרה'] != "" else 1.0
                        except:
                            factor = 1.0
                        total = final_q * factor
                        display_q = int(total) if total.is_integer() else total
                        order_lines.append(f"• {p}: {display_q} {row['יחידת הזמנה']}")
                
                if st.button(f"צור הודעה וסגור משימה ({s})", key=f"msg_btn_{idx}"):
                    full_msg = f"היי, כאן מפיצטה.\nנשמח להזמין ל-{s}:\n" + "\n".join(order_lines) + "\nתודה!"
                    st.session_state[f"final_msg_{idx}"] = full_msg
                    arch_ws = sh.worksheet("Archive")
                    arch_ws.append_row([datetime.now().strftime("%d/%m/%Y"), s, full_msg])
                    tasks_ws.delete_rows(idx + 2)
                    st.rerun()

                if f"final_msg_{idx}" in st.session_state:
                    st.text_area("הודעה להעתקה:", st.session_state[f"final_msg_{idx}"], height=150)

# --- 4. ארכיון ועריכת קטלוג ---
elif choice == "ארכיון":
    st.header("📜 היסטוריית הזמנות")
    df_arch = pd.DataFrame(sh.worksheet("Archive").get_all_records())
    st.dataframe(df_arch, use_container_width=True)

elif choice == "עריכת קטלוג":
    st.header("⚙️ עריכת נתוני מוצרים")
    inv_ws = sh.worksheet("Inventory")
    df_inv = pd.DataFrame(inv_ws.get_all_records())
    edited = st.data_editor(df_inv, num_rows="dynamic", use_container_width=True)
    if st.button("שמור שינויים"):
        inv_ws.update([edited.columns.values.tolist()] + edited.values.tolist(), value_input_option='RAW')
        st.success("עודכן!")
