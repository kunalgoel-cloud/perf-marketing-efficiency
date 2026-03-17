import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import io
import plotly.graph_objects as go

# --- 1. DATABASE SETUP (STABLE CONFIG) ---
try:
    DB_URL = st.secrets["SUPABASE_DB_URL"]
    
    # Engine configured to bypass common pooling handshake issues
    engine = create_engine(
        DB_URL,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={
            "sslmode": "require",
            "connect_timeout": 10,
            # This is the critical fix for the pooling driver error
            "options": "-c prepare_threshold=0"
        }
    )
except Exception as e:
    st.error(f"Database setup error: {e}")
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
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: continue
    return None

def standardize_data(df):
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'Date': 'date'
    }
    df = df.rename(columns=mapping)
    for col in ['spend', 'sales']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    return df.dropna(subset=['date'])

# --- 3. LOGIN ---
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
                    conn.commit()
                st.rerun()
            st.dataframe(pd.read_sql("SELECT name FROM channels", engine), hide_index=True)
        with c2:
            st.subheader("Products")
            new_pr = st.text_input("New Product")
            if st.button("Add Product"):
                with engine.connect() as conn:
                    conn.execute(text("INSERT INTO products (name) VALUES (:n) ON CONFLICT DO NOTHING"), {"n": new_pr})
                    conn.commit()
                st.rerun()
            st.dataframe(pd.read_sql("SELECT name FROM products", engine), hide_index=True)

# --- 5. UPLOAD ---
elif choice == "Upload Reports":
    st.header("📥 Upload Data")
    chs = pd.read_sql("SELECT name FROM channels", engine)['name'].tolist()
    sel_ch = st.selectbox("Channel", chs)
    file = st.file_uploader("Choose File", type=['csv', 'xlsx'])
    
    if file:
        df = standardize_data(robust_read_file(file))
        df_m = pd.read_sql("SELECT * FROM mappings", engine)
        maps = df_m.groupby('campaign')['product_name'].apply(list).to_dict()
        unmapped = [c for c in df['campaign'].unique() if c not in maps]
        
        if unmapped:
            st.warning(f"Map {len(unmapped)} campaigns")
            prods = pd.read_sql("SELECT name FROM products", engine)['name'].tolist() + ["Brand"]
            with st.form("m"):
                nm = {c: st.multiselect(f"Map {c}", prods) for c in unmapped}
                if st.form_submit_button("Save"):
                    with engine.connect() as conn:
                        for cp, pl in nm.items():
                            for p in pl: conn.execute(text("INSERT INTO mappings VALUES (:c,:p)"), {"c":cp, "p":p})
                        conn.commit()
                    st.rerun()
        else:
            if st.button("🚀 Sync to Supabase"):
                with engine.connect() as conn:
                    for _, row in df.iterrows():
                        targets = maps.get(row['campaign'], ["Unmapped"])
                        for t in targets:
                            conn.execute(text("INSERT INTO performance (date, channel, campaign, product, spend, sales) VALUES (:d,:c,:cp,:p,:s,:sl)"),
                                         {"d":row['date'], "c":sel_ch, "cp":row['campaign'], "p":t, "s":row['spend']/len(targets), "sl":row['sales']/len(targets)})
                    conn.commit()
                st.success("Uploaded!")

# --- 6. DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Dashboard")
    # This line triggered the original error
    df_p = pd.read_sql("SELECT * FROM performance", engine) 
    
    if not df_p.empty:
        df_p['date'] = pd.to_datetime(df_p['date'])
        ch_f = st.sidebar.multiselect("Channels", df_p['channel'].unique(), default=df_p['channel'].unique())
        f_df = df_p[df_p['channel'].isin(ch_f)]
        
        c1, c2, c3 = st.columns(3)
        s, r = f_df['spend'].sum(), f_df['sales'].sum()
        c1.metric("Spend", f"₹{s:,.0f}")
        c2.metric("Revenue", f"₹{r:,.0f}")
        c3.metric("ROAS", f"{(r/s):.2f}x" if s > 0 else "0.00x")
        
        st.bar_chart(f_df.groupby('date')['spend'].sum())
    else:
        st.info("No data yet. Go to 'Upload Reports'.")
