import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import io
import plotly.graph_objects as go

# --- 1. DATABASE SETUP ---
try:
    DB_URL = st.secrets["SUPABASE_DB_URL"]
    engine = create_engine(
        DB_URL,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"sslmode": "require", "connect_timeout": 10}
    )
except Exception as e:
    st.error("Database connection configuration error.")
    st.stop()

# --- 2. DATA UTILITIES ---
def robust_read_file(file):
    file_name = file.name.lower()
    if file_name.endswith(('.xlsx', '.xls')):
        return pd.read_excel(file)
    bytes_data = file.read()
    for enc in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            df_check = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, nrows=10)
            if 'METRICS_DATE' in df_check.columns:
                return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
            if any("Selected Filters" in str(col) for col in df_check.columns):
                 return pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: continue
    return None

def standardize_data(df, manual_date=None):
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'Campaign name': 'campaign', 
        'Total cost': 'spend', 'Sales': 'sales', 
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales'
    }
    df = df.rename(columns=mapping)
    if 'campaign' not in df.columns: df['campaign'] = "CHANNEL_TOTAL"
    for col in ['spend', 'sales']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    df = df[df['spend'] > 0].copy()
    if manual_date:
        df['date'] = pd.to_datetime(manual_date)
    else:
        df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    return df.dropna(subset=['date'])[['date', 'campaign', 'spend', 'sales']]

# --- 3. AUTH ---
if 'auth' not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("🛡️ Marketing Efficiency Portal")
    u, p = st.text_input("User"), st.text_input("Password", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth, st.session_state.role = True, u
            st.rerun()
    st.stop()

choice = st.sidebar.selectbox("Navigation", ["Dashboard", "Upload Reports", "Settings"] if st.session_state.role == "admin" else ["Dashboard"])

# --- 4. SETTINGS ---
if choice == "Settings":
    st.header("⚙️ Settings")
    t1, t2 = st.tabs(["Master Data", "Mappings"])
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Channels")
            new_ch = st.text_input("New Channel")
            if st.button("Add"):
                with engine.connect() as conn:
                    conn.execute(text("INSERT INTO channels (name) VALUES (:n) ON CONFLICT DO NOTHING"), {"n": new_ch})
                st.rerun()
            st.dataframe(pd.read_sql("SELECT name FROM channels", engine), hide_index=True)
        with c2:
            st.subheader("Products")
            new_pr = st.text_input("New Product")
            if st.button("Add Product"):
                with engine.connect() as conn:
                    conn.execute(text("INSERT INTO products (name) VALUES (:n) ON CONFLICT DO NOTHING"), {"n": new_pr})
                st.rerun()
            st.dataframe(pd.read_sql("SELECT name FROM products", engine), hide_index=True)

# --- 5. UPLOAD ---
elif choice == "Upload Reports":
    st.header("📥 Upload")
    chs = pd.read_sql("SELECT name FROM channels", engine)['name'].tolist()
    sel_ch = st.selectbox("Channel", chs)
    file = st.file_uploader("File", type=['csv', 'xlsx'])
    if file:
        df = standardize_data(robust_read_file(file))
        df_m = pd.read_sql("SELECT * FROM mappings", engine)
        maps = df_m.groupby('campaign')['product_name'].apply(list).to_dict()
        unmapped = [c for c in df['campaign'].unique() if c not in maps]
        if unmapped:
            st.warning("Mapping Required")
            prods = pd.read_sql("SELECT name FROM products", engine)['name'].tolist() + ["Brand"]
            with st.form("f"):
                nm = {c: st.multiselect(f"Map {c}", prods) for c in unmapped}
                if st.form_submit_button("Save"):
                    with engine.connect() as conn:
                        for cp, pl in nm.items():
                            for p in pl: conn.execute(text("INSERT INTO mappings VALUES (:c, :p)"), {"c": cp, "p": p})
                    st.rerun()
        else:
            if st.button("🚀 Push to Cloud"):
                with engine.connect() as conn:
                    for _, row in df.iterrows():
                        targets = maps.get(row['campaign'], ["Unmapped"])
                        for t in targets:
                            conn.execute(text("INSERT INTO performance (date, channel, campaign, product, spend, sales) VALUES (:d,:c,:cp,:p,:s,:sl)"),
                                         {"d":row['date'], "c":sel_ch, "cp":row['campaign'], "p":t, "s":row['spend']/len(targets), "sl":row['sales']/len(targets)})
                st.success("Uploaded")

# --- 6. DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Dashboard")
    df_p = pd.read_sql("SELECT * FROM performance", engine)
    if not df_p.empty:
        df_p['date'] = pd.to_datetime(df_p['date'])
        # Simplified filters for testing
        ch_f = st.sidebar.multiselect("Filter Channel", df_p['channel'].unique(), default=df_p['channel'].unique())
        f_df = df_p[df_p['channel'].isin(ch_f)]
        
        c1, c2 = st.columns(2)
        c1.metric("Spend", f"₹{f_df['spend'].sum():,.0f}")
        c2.metric("Revenue", f"₹{f_df['sales'].sum():,.0f}")
        
        st.bar_chart(f_df.groupby('date')['spend'].sum())
    else:
        st.info("No data yet.")
