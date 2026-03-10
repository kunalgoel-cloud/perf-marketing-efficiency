import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go

# --- DATABASE SETUP ---
# Using v6 to ensure a clean schema for multi-product mapping
conn = sqlite3.connect('marketing_v6.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
# Mapping table now supports multiple products per campaign
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
            # Check for Instamart/Swiggy header offset
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
    
    # Requirement: Remove campaigns with zero spend
    if 'spend' in df.columns:
        # Clean numeric data before filtering
        for col in ['spend', 'sales', 'clicks', 'orders']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
        
        df = df[df['spend'] > 0].copy()
    
    if 'campaign' not in df.columns: df['campaign'] = "CHANNEL_TOTAL"
    
    # Ensure all required columns exist
    for col in ['spend', 'sales', 'clicks', 'orders']:
        if col not in df.columns: df[col] = 0.0
        
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    return df[['date', 'campaign', 'spend', 'sales', 'clicks', 'orders']]

# --- AUTH ---
if 'auth' not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("Performance Marketing Login")
    u, p = st.text_input("Username"), st.text_input("Password", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth, st.session_state.role = True, u
            st.rerun()
    st.stop()

# --- MENU ---
menu = ["Dashboard", "Upload Reports", "System Settings"] if st.session_state.role == "admin" else ["Dashboard"]
choice = st.sidebar.selectbox("Navigation", menu)

# --- CONFIGURATION ---
if choice == "System Settings":
    st.header("Configure Products & Channels")
    col1, col2 = st.columns(2)
    with col1:
        new_ch = st.text_input("New Channel Name")
        if st.button("Add Channel"): 
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
            conn.commit()
        st.write("**Current Channels:**", pd.read_sql("SELECT name FROM channels", conn))
    with col2:
        new_pr = st.text_input("New Product Name")
        if st.button("Add Product"): 
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
            conn.commit()
        st.write("**Current Products:**", pd.read_sql("SELECT name FROM products", conn))

# --- DATA UPLOAD ---
elif choice == "Upload Reports":
    st.header("Upload Ad Data")
    channels = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
    selected_ch = st.selectbox("Select Channel", channels)
    file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])

    if file:
        raw_df = robust_read_file(file)
        if raw_df is not None:
            df = standardize_data(raw_df)
            st.success(f"File read! {len(df)} rows found with Spend > 0.")
            
            # Fetch existing mappings
            known_mappings = {}
            for row in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
                known_mappings.setdefault(row[0], []).append(row[1])
            
            unique_camps = df['campaign'].unique()
            unmapped = [cp for cp in unique_camps if cp not in known_mappings]

            if unmapped:
                st.warning(f"New campaigns detected ({len(unmapped)}). Please map them below.")
                all_products = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                
                new_map_data = []
                for camp in unmapped:
                    selected_prods = st.multiselect(f"Map products for: {camp}", all_products, key=camp)
                    if selected_prods:
                        new_map_data.append((camp, selected_prods))
                
                if st.button("Confirm Mappings & Process"):
                    for camp, prod_list in new_map_data:
                        for p_name in prod_list:
                            c.execute("INSERT OR IGNORE INTO mappings VALUES (?,?)", (camp, p_name))
                    conn.commit()
                    st.rerun()
            else:
                if st.button("Process & Save Data"):
                    # Process and split data
                    for _, row in df.iterrows():
                        target_products = known_mappings.get(row['campaign'], ["Unmapped"])
                        n = len(target_products)
                        # Split metrics equally
                        split_spend = row['spend'] / n
                        split_sales = row['sales'] / n
                        split_clicks = row['clicks'] / n
                        split_orders = row['orders'] / n
                        
                        for prod in target_products:
                            c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", 
                                      (row['date'], selected_ch, row['campaign'], prod, split_spend, split_sales, split_clicks, split_orders))
                    conn.commit()
                    st.success("Data split and saved to dashboard!")

# --- DASHBOARD ---
elif choice == "Dashboard":
    st.header("Marketing Efficiency Dashboard")
    df_perf = pd.read_sql("SELECT * FROM performance", conn)

    if df_perf.empty:
        st.info("No data available. Please upload reports via the Admin login.")
    else:
        # Filters
        st.sidebar.header("Filters")
        ch_filter = st.sidebar.multiselect("Channels", df_perf['channel'].unique(), default=df_perf['channel'].unique())
        pr_filter = st.sidebar.multiselect("Products", df_perf['product'].unique(), default=df_perf['product'].unique())
        
        f_df = df_perf[(df_perf['channel'].isin(ch_filter)) & (df_perf['product'].isin(pr_filter))]

        # Metrics
        total_spend = f_df['spend'].sum()
        total_sales = f_df['sales'].sum()
        roas = total_sales / total_spend if total_spend > 0 else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Spend", f"₹{total_spend:,.0f}")
        c2.metric("Total Sales", f"₹{total_sales:,.0f}")
        c3.metric("Total ROAS", f"{roas:.2f}x")

        # Trend Line
        st.subheader("Performance Over Time")
        trend = f_df.groupby('date').agg({'spend':'sum', 'sales':'sum'}).reset_index()
        trend['ROAS'] = trend['sales'] / trend['spend']
        
        fig = go.Figure()
        fig.add_trace(go.Bar(x=trend['date'], y=trend['spend'], name="Ad Spend", marker_color='#4A90E2'))
        fig.add_trace(go.Scatter(x=trend['date'], y=trend['ROAS'], name="ROAS", yaxis="y2", line=dict(color='#E94E77', width=3)))
        fig.update_layout(yaxis=dict(title="Spend (₹)"), yaxis2=dict(title="ROAS", overlaying="y", side="right"), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)

        # Breakdowns
        col_l, col_r = st.columns(2)
        with col_l:
            st.write("**Channel Efficiency**")
            st.dataframe(f_df.groupby('channel').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False), use_container_width=True)
        with col_r:
            st.write("**Product Efficiency**")
            st.dataframe(f_df.groupby('product').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False), use_container_width=True)
