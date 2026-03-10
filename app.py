import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go

# --- DATABASE SETUP ---
# Incremented version to ensure schema compatibility for multi-mapping
conn = sqlite3.connect('marketing_v7.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
# Campaign to Product is now Many-to-Many
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT, product_name TEXT, UNIQUE(campaign, product_name))')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL, clicks REAL, orders REAL)')
conn.commit()

# --- UTILS & PARSING ---
def robust_read_file(file):
    file_name = file.name.lower()
    if file_name.endswith(('.xlsx', '.xls')):
        return pd.read_excel(file)
    
    bytes_data = file.read()
    for enc in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            # Buffer check for Swiggy metadata
            df_check = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, nrows=10)
            if 'METRICS_DATE' not in df_check.columns and any("Selected Filters" in str(col) for col in df_check.columns):
                 return pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: continue
    return None

def standardize_data(df):
    # Mapping for Swiggy (TOTAL_BUDGET_BURNT), Amazon (Total cost), and Others
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'TOTAL_CLICKS': 'clicks', 'TOTAL_CONVERSIONS': 'orders',
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 
        'Campaign start date': 'date', 'Clicks': 'clicks', 'Purchases': 'orders',
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales', 'Ad Clicks': 'clicks', 'Orders (SKU)': 'orders'
    }
    df = df.rename(columns=mapping)
    
    # Ensure mandatory columns exist for numeric cleaning
    for col in ['spend', 'sales', 'clicks', 'orders']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    # 1. REMOVE ZERO SPEND CAMPAIGNS
    df = df[df['spend'] > 0].copy()
    
    if 'campaign' not in df.columns: df['campaign'] = "CHANNEL_TOTAL"
    
    # 2. FIXED DATE PARSING (Handles DD/MM/YYYY and YYYY-MM-DD automatically)
    df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['date']) # Drop rows where date couldn't be parsed
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    
    return df[['date', 'campaign', 'spend', 'sales', 'clicks', 'orders']]

# --- AUTH & UI ---
if 'auth' not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("Performance Marketing Dashboard")
    u, p = st.text_input("User"), st.text_input("Pass", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth, st.session_state.role = True, u
            st.rerun()
    st.stop()

choice = st.sidebar.selectbox("Navigation", ["Dashboard", "Upload", "Settings"] if st.session_state.role == "admin" else ["Dashboard"])

# --- SETTINGS ---
if choice == "Settings":
    st.header("Configurations")
    col1, col2 = st.columns(2)
    with col1:
        new_ch = st.text_input("Add Channel")
        if st.button("Add"): c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,)); conn.commit()
        st.write(pd.read_sql("SELECT name FROM channels", conn))
    with col2:
        new_pr = st.text_input("Add Product")
        if st.button("Add "): c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,)); conn.commit()
        st.write(pd.read_sql("SELECT name FROM products", conn))

# --- UPLOAD ---
elif choice == "Upload":
    st.header("Upload Ad Reports")
    chs = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
    sel_ch = st.selectbox("Channel", chs)
    file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])

    if file:
        df = standardize_data(robust_read_file(file))
        st.success(f"File processed. Found {len(df)} active campaigns.")
        
        # Mapping Logic
        mapping_db = {}
        for row in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
            mapping_db.setdefault(row[0], []).append(row[1])
        
        unmapped = [cp for cp in df['campaign'].unique() if cp not in mapping_db]
        
        if unmapped:
            st.warning(f"{len(unmapped)} New Campaigns Found. Map them to one or more products.")
            prods = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
            
            for cp in unmapped:
                selected = st.multiselect(f"Assign product(s) for: {cp}", prods, key=cp)
                if selected:
                    for p_name in selected:
                        c.execute("INSERT OR IGNORE INTO mappings VALUES (?,?)", (cp, p_name))
            
            if st.button("Confirm Mappings"):
                conn.commit()
                st.rerun()
        else:
            if st.button("Save Data to Dashboard"):
                for _, row in df.iterrows():
                    target_prods = mapping_db.get(row['campaign'], ["Unmapped"])
                    n = len(target_prods)
                    # MULTI-PRODUCT SPLIT LOGIC
                    for p_name in target_prods:
                        c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", 
                                  (row['date'], sel_ch, row['campaign'], p_name, row['spend']/n, row['sales']/n, row['clicks']/n, row['orders']/n))
                conn.commit()
                st.success("Data stored!")

# --- DASHBOARD ---
elif choice == "Dashboard":
    st.header("Analytics")
    df_perf = pd.read_sql("SELECT * FROM performance", conn)
    if not df_perf.empty:
        # Filters & Charts (Same as previous consolidated code)
        total_spend = df_perf['spend'].sum()
        total_sales = df_perf['sales'].sum()
        st.metric("Total ROAS", f"{(total_sales/total_spend):.2f}x")
        # [Charts Logic...]
