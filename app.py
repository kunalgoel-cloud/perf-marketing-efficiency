import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go

# --- 1. DATABASE SETUP ---
# Incremented to v9 to ensure schema supports multi-product mapping
conn = sqlite3.connect('marketing_v9_final.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
# Campaign mapping: allows one campaign to many products
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT, product_name TEXT, UNIQUE(campaign, product_name))')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL, clicks REAL, orders REAL)')
conn.commit()

# --- 2. DATA PARSING ENGINE ---
def robust_read_file(file):
    file_name = file.name.lower()
    if file_name.endswith(('.xlsx', '.xls')):
        return pd.read_excel(file)
    
    bytes_data = file.read()
    for enc in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            # Check for Swiggy/Instamart metadata offset
            df_check = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, nrows=10)
            if 'METRICS_DATE' not in df_check.columns and any("Selected Filters" in str(col) for col in df_check.columns):
                 return pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: continue
    return None

def standardize_data(df, manual_date=None):
    # Mapping for Swiggy, Amazon, and Generic Performance Summaries
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'TOTAL_CLICKS': 'clicks', 'TOTAL_CONVERSIONS': 'orders',
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 
        'Campaign start date': 'date', 'Clicks': 'clicks', 'Purchases': 'orders',
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales', 'Ad Clicks': 'clicks', 'Orders (SKU)': 'orders'
    }
    df = df.rename(columns=mapping)
    
    # Numeric Cleaning
    for col in ['spend', 'sales', 'clicks', 'orders']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    # REQ: Remove zero spend campaigns
    df = df[df['spend'] > 0].copy()

    # DATE LOGIC: Priority to Manual Date > File Date
    if manual_date:
        df['date'] = manual_date.strftime('%Y-%m-%d')
    else:
        df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['date'])
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    
    if 'campaign' not in df.columns: df['campaign'] = "CHANNEL_TOTAL"
    return df[['date', 'campaign', 'spend', 'sales', 'clicks', 'orders']]

# --- 3. AUTHENTICATION ---
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ Marketing Control Center")
    u, p = st.text_input("User"), st.text_input("Password", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth, st.session_state.role = True, u
            st.rerun()
    st.stop()

# --- 4. NAVIGATION ---
choice = st.sidebar.selectbox("Navigation", ["Dashboard", "Upload Reports", "Settings"] if st.session_state.role == "admin" else ["Dashboard"])

# --- SETTINGS: Manage Master Data ---
if choice == "Settings":
    st.header("⚙️ System Configurations")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Channels")
        new_ch = st.text_input("Add Channel (e.g. Swiggy)")
        if st.button("Save Channel"): 
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name FROM channels", conn), hide_index=True)
    with col2:
        st.subheader("Products")
        new_pr = st.text_input("Add Product (e.g. Patal Poha)")
        if st.button("Save Product"): 
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name FROM products", conn), hide_index=True)

# --- UPLOAD: Process & Map Data ---
elif choice == "Upload Reports":
    st.header("📥 Data Ingestion")
    
    c_date, c_chan = st.columns(2)
    with c_date:
        manual_date = st.date_input("Manual Date Override (Optional)", value=None)
    with c_chan:
        chs = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
        sel_ch = st.selectbox("Target Channel", chs)
    
    file = st.file_uploader("Upload Ad Report", type=['csv', 'xlsx'])

    if file:
        raw_df = robust_read_file(file)
        if raw_df is not None:
            df = standardize_data(raw_df, manual_date=manual_date)
            st.info(f"Processed {len(df)} active campaigns for {sel_ch}.")
            
            # Load existing mappings
            mappings = {}
            for row in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
                mappings.setdefault(row[0], []).append(row[1])
            
            unmapped = [cp for cp in df['campaign'].unique() if cp not in mappings]
            
            if unmapped:
                st.warning(f"⚠️ {len(unmapped)} New Campaigns require product mapping.")
                prods = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                
                with st.form("mapping_form"):
                    new_entries = {}
                    for cp in unmapped:
                        new_entries[cp] = st.multiselect(f"Products for: {cp}", prods)
                    
                    if st.form_submit_button("Confirm & Save Mappings"):
                        for cp, p_list in new_entries.items():
                            for p_name in p_list:
                                c.execute("INSERT OR IGNORE INTO mappings VALUES (?,?)", (cp, p_name))
                        conn.commit()
                        st.rerun()
            else:
                if st.button("🚀 Finalize & Save to Dashboard"):
                    for _, row in df.iterrows():
                        target_prods = mappings.get(row['campaign'], ["Unmapped"])
                        n = len(target_prods)
                        # SPLIT LOGIC: Equal distribution across products
                        for p_name in target_prods:
                            c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", 
                                      (row['date'], sel_ch, row['campaign'], p_name, row['spend']/n, row['sales']/n, row['clicks']/n, row['orders']/n))
                    conn.commit()
                    st.success("Data successfully recorded!")

# --- DASHBOARD: Visualize ROI ---
elif choice == "Dashboard":
    st.header("📊 Performance Analytics")
    df_p = pd.read_sql("SELECT * FROM performance", conn)

    if df_p.empty:
        st.warning("No data found. Please upload reports in the Admin section.")
    else:
        # Sidebar Filters
        st.sidebar.subheader("Filters")
        ch_f = st.sidebar.multiselect("Channels", df_p['channel'].unique(), default=df_p['channel'].unique())
        pr_f = st.sidebar.multiselect("Products", df_p['product'].unique(), default=df_p['product'].unique())
        
        f_df = df_p[(df_p['channel'].isin(ch_f)) & (df_p['product'].isin(pr_f))]

        # Scorecards
        t_spend, t_sales = f_df['spend'].sum(), f_df['sales'].sum()
        roas = t_sales / t_spend if t_spend > 0 else 0
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Ad Spend", f"₹{t_spend:,.0f}")
        k2.metric("Revenue", f"₹{t_sales:,.0f}")
        k3.metric("ROAS", f"{roas:.2f}x")

        # Trend Chart
        
        trend = f_df.groupby('date').agg({'spend':'sum', 'sales':'sum'}).reset_index()
        trend['ROAS'] = trend['sales'] / trend['spend']
        
        fig = go.Figure()
        fig.add_trace(go.Bar(x=trend['date'], y=trend['spend'], name="Spend", marker_color='#3498db'))
        fig.add_trace(go.Scatter(x=trend['date'], y=trend['ROAS'], name="ROAS", yaxis="y2", line=dict(color='#e74c3c', width=3)))
        fig.update_layout(yaxis=dict(title="Spend (₹)"), yaxis2=dict(title="ROAS", overlaying="y", side="right"), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)

        # Breakdowns
        st.subheader("Efficiency Deep Dive")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**By Channel**")
            st.dataframe(f_df.groupby('channel').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False))
        with c2:
            st.write("**By Product**")
            st.dataframe(f_df.groupby('product').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False))
