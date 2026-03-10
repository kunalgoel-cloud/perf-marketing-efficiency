import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go

# --- DATABASE SETUP ---
conn = sqlite3.connect('marketing_v5.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT PRIMARY KEY, product_name TEXT)')
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
            df = pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
            if 'METRICS_DATE' not in df.columns and 'Selected Filters' in str(df.columns):
                 df = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return df
        except: continue
    return None

def standardize_data(df):
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 'TOTAL_SPEND': 'spend', 'TOTAL_GMV': 'sales', 'TOTAL_CLICKS': 'clicks', 'TOTAL_CONVERSIONS': 'orders',
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 'Campaign start date': 'date', 'Clicks': 'clicks', 'Purchases': 'orders',
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales', 'Ad Clicks': 'clicks', 'Orders (SKU)': 'orders'
    }
    df = df.rename(columns=mapping)
    if 'campaign' not in df.columns: df['campaign'] = "CHANNEL_TOTAL"
    for col in ['spend', 'sales', 'clicks', 'orders']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
        else:
            df[col] = 0.0
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    return df[['date', 'campaign', 'spend', 'sales', 'clicks', 'orders']]

# --- AUTH ---
if 'auth' not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("Marketing Login")
    u, p = st.text_input("User"), st.text_input("Pass", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth, st.session_state.role = True, u
            st.rerun()
    st.stop()

# --- MENU ---
menu = ["Analytics Dashboard", "Data Upload", "Configuration"] if st.session_state.role == "admin" else ["Analytics Dashboard"]
choice = st.sidebar.selectbox("Navigate", menu)

# --- 1. CONFIGURATION ---
if choice == "Configuration":
    st.header("Settings")
    col1, col2 = st.columns(2)
    with col1:
        new_ch = st.text_input("Add Channel")
        if st.button("Save Channel"): 
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name as Channels FROM channels", conn), hide_index=True)
    with col2:
        new_pr = st.text_input("Add Product")
        if st.button("Save Product"): 
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name as Products FROM products", conn), hide_index=True)

# --- 2. DATA UPLOAD ---
elif choice == "Data Upload":
    st.header("Upload Ad Reports")
    channels = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
    selected_ch = st.selectbox("Select Channel", channels)
    file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])

    if file:
        df = standardize_data(robust_read_file(file))
        mapping_db = dict(c.execute("SELECT campaign, product_name FROM mappings").fetchall())
        unmapped = [cp for cp in df['campaign'].unique() if cp not in mapping_db]

        if unmapped:
            st.warning(f"Map {len(unmapped)} New Campaigns")
            prods = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
            map_df = pd.DataFrame({'campaign': unmapped, 'product_name': [None]*len(unmapped)})
            res = st.data_editor(map_df, column_config={"product_name": st.column_config.SelectboxColumn("Product", options=prods, required=True)}, hide_index=True)
            if st.button("Save Data"):
                for _, row in res.iterrows():
                    if row['product_name']: c.execute("INSERT OR REPLACE INTO mappings VALUES (?,?)", (row['campaign'], row['product_name']))
                # Save actual performance rows
                for _, row in df.iterrows():
                    prod = dict(c.execute("SELECT campaign, product_name FROM mappings").fetchall()).get(row['campaign'], "Unmapped")
                    c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", (row['date'], selected_ch, row['campaign'], prod, row['spend'], row['sales'], row['clicks'], row['orders']))
                conn.commit()
                st.success("Data Uploaded Successfully!")

# --- 3. ANALYTICS DASHBOARD ---
elif choice == "Analytics Dashboard":
    st.header("Performance Marketing Insights")
    df_perf = pd.read_sql("SELECT * FROM performance", conn)

    if df_perf.empty:
        st.info("No data available. Admin needs to upload reports.")
    else:
        # Side Filters
        st.sidebar.header("Filters")
        ch_filter = st.sidebar.multiselect("Channels", df_perf['channel'].unique(), default=df_perf['channel'].unique())
        pr_filter = st.sidebar.multiselect("Products", df_perf['product'].unique(), default=df_perf['product'].unique())
        
        f_df = df_perf[(df_perf['channel'].isin(ch_filter)) & (df_perf['product'].isin(pr_filter))]

        # KPI SCORECARDS
        total_spend = f_df['spend'].sum()
        total_sales = f_df['sales'].sum()
        roas = total_sales / total_spend if total_spend > 0 else 0
        avg_cpc = total_spend / f_df['clicks'].sum() if f_df['clicks'].sum() > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Spend", f"₹{total_spend:,.0f}")
        c2.metric("Total Sales", f"₹{total_sales:,.0f}")
        c3.metric("ROAS", f"{roas:.2f}x")
        c4.metric("Avg CPC", f"₹{avg_cpc:.2f}")

        # TREND GRAPH
        st.subheader("Efficiency Trend Line")
        trend = f_df.groupby('date').agg({'spend':'sum', 'sales':'sum'}).reset_index()
        trend['ROAS'] = trend['sales'] / trend['spend']

        fig = go.Figure()
        fig.add_trace(go.Bar(x=trend['date'], y=trend['spend'], name="Ad Spend", marker_color='#4A90E2'))
        fig.add_trace(go.Scatter(x=trend['date'], y=trend['ROAS'], name="ROAS", yaxis="y2", line=dict(color='#E94E77', width=3)))
        fig.update_layout(yaxis=dict(title="Spend"), yaxis2=dict(title="ROAS", overlaying="y", side="right"), legend=dict(orientation="h", y=1.1))
        st.plotly_chart(fig, use_container_width=True)

        # PRODUCT & CHANNEL TABLES
        st.subheader("Deep Dive Breakdown")
        col_a, col_b = st.columns(2)
        with col_a:
            st.write("**By Product**")
            p_tab = f_df.groupby('product').agg({'spend':'sum', 'sales':'sum'}).reset_index()
            p_tab['ROAS'] = p_tab['sales'] / p_tab['spend']
            st.dataframe(p_tab.sort_values(by='ROAS', ascending=False), hide_index=True)
        with col_b:
            st.write("**By Channel**")
            c_tab = f_df.groupby('channel').agg({'spend':'sum', 'sales':'sum'}).reset_index()
            c_tab['ROAS'] = c_tab['sales'] / c_tab['spend']
            st.dataframe(c_tab.sort_values(by='ROAS', ascending=False), hide_index=True)
