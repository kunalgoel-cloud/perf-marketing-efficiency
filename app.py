import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. DATABASE SETUP ---
conn = sqlite3.connect('marketing_v10_final.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT, product_name TEXT, UNIQUE(campaign, product_name))')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL, clicks REAL, orders REAL)')
conn.commit()

# --- 2. DATA PROCESSING ENGINE ---
def robust_read_file(file):
    file_name = file.name.lower()
    if file_name.endswith(('.xlsx', '.xls')):
        return pd.read_excel(file)
    bytes_data = file.read()
    for enc in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            df_check = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, nrows=10)
            if 'METRICS_DATE' not in df_check.columns and any("Selected Filters" in str(col) for col in df_check.columns):
                 return pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: continue
    return None

def standardize_data(df, manual_date=None):
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'TOTAL_CLICKS': 'clicks', 'TOTAL_CONVERSIONS': 'orders',
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 
        'Campaign start date': 'date', 'Clicks': 'clicks', 'Purchases': 'orders',
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales', 'Ad Clicks': 'clicks', 'Orders (SKU)': 'orders'
    }
    df = df.rename(columns=mapping)
    for col in ['spend', 'sales', 'clicks', 'orders']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    df = df[df['spend'] > 0].copy()
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
    st.title("🛡️ Marketing Analytics Login")
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
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Manage Channels")
        new_ch = st.text_input("New Channel")
        if st.button("Add Channel"): 
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name FROM channels", conn), hide_index=True)
    with col2:
        st.subheader("Manage Products")
        new_pr = st.text_input("New Product")
        if st.button("Add Product"): 
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name FROM products", conn), hide_index=True)

    st.divider()
    st.subheader("🗑️ Delete Data")
    d_col1, d_col2 = st.columns(2)
    with d_col1:
        chs = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
        target_ch = st.selectbox("Channel to Delete", ["Select"] + chs)
    with d_col2:
        target_date = st.date_input("Date to Delete", value=None)
    if st.button("Execute Deletion", type="primary"):
        if target_ch != "Select" and target_date:
            d_str = target_date.strftime('%Y-%m-%d')
            c.execute("DELETE FROM performance WHERE channel=? AND date=?", (target_ch, d_str))
            conn.commit()
            st.warning(f"Cleared {target_ch} for {d_str}")

# --- 5. UPLOAD ---
elif choice == "Upload Reports":
    st.header("📥 Upload Reports")
    u_col1, u_col2 = st.columns(2)
    with u_col1:
        manual_date = st.date_input("Date Override (Optional)", value=None)
    with u_col2:
        chs = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
        sel_ch = st.selectbox("Source Channel", chs)
    
    file = st.file_uploader("Choose CSV/Excel", type=['csv', 'xlsx'])
    if file:
        raw_df = robust_read_file(file)
        if raw_df is not None:
            df = standardize_data(raw_df, manual_date=manual_date)
            mappings = {r[0]: [] for r in c.execute("SELECT DISTINCT campaign FROM mappings").fetchall()}
            for r in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
                mappings[r[0]].append(r[1])
            
            unmapped = [cp for cp in df['campaign'].unique() if cp not in mappings]
            if unmapped:
                st.warning(f"Map {len(unmapped)} campaigns")
                prods = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                with st.form("map"):
                    new_maps = {cp: st.multiselect(f"Map: {cp}", prods) for cp in unmapped}
                    if st.form_submit_button("Save Mappings"):
                        for cp, pl in new_maps.items():
                            for pn in pl: c.execute("INSERT INTO mappings VALUES (?,?)", (cp, pn))
                        conn.commit(); st.rerun()
            else:
                if st.button("Finalize Upload"):
                    for _, row in df.iterrows():
                        target_prods = mappings.get(row['campaign'], ["Unmapped"])
                        n = len(target_prods)
                        for p_name in target_prods:
                            c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", (row['date'], sel_ch, row['campaign'], p_name, row['spend']/n, row['sales']/n, row['clicks']/n, row['orders']/n))
                    conn.commit(); st.success("Data stored!")

# --- 6. DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Performance Dashboard")
    df_p = pd.read_sql("SELECT * FROM performance", conn)
    if df_p.empty:
        st.info("No data available.")
    else:
        df_p['date'] = pd.to_datetime(df_p['date'])
        
        # SIDEBAR FILTERS
        st.sidebar.subheader("Filters")
        
        # 1. Date Range Filter
        min_d, max_d = df_p['date'].min().date(), df_p['date'].max().date()
        date_range = st.sidebar.date_input("Select Date Range", value=(min_d, max_d), min_value=min_d, max_value=max_d)
        
        # 2. Multi-select Filters
        ch_f = st.sidebar.multiselect("Channels", df_p['channel'].unique(), default=df_p['channel'].unique())
        pr_f = st.sidebar.multiselect("Products", df_p['product'].unique(), default=df_p['product'].unique())

        # APPLY FILTERS
        if len(date_range) == 2:
            start_d, end_d = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
            f_df = df_p[(df_p['date'] >= start_d) & (df_p['date'] <= end_d) & (df_p['channel'].isin(ch_f)) & (df_p['product'].isin(pr_f))]
        else:
            f_df = df_p[(df_p['channel'].isin(ch_f)) & (df_p['product'].isin(pr_f))]

        # KPIs
        t_spend, t_sales = f_df['spend'].sum(), f_df['sales'].sum()
        roas = t_sales / t_spend if t_spend > 0 else 0
        k1, k2, k3 = st.columns(3)
        k1.metric("Spend", f"₹{t_spend:,.0f}")
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

        # Tabular Views
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.write("**By Channel**")
            ch_tab = f_df.groupby('channel').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False)
            st.dataframe(ch_tab.style.format({'spend':'₹{:,.0f}', 'sales':'₹{:,.0f}', 'ROAS':'{:.2f}x'}), use_container_width=True)
        with c2:
            st.write("**By Product**")
            pr_tab = f_df.groupby('product').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False)
            st.dataframe(pr_tab.style.format({'spend':'₹{:,.0f}', 'sales':'₹{:,.0f}', 'ROAS':'{:.2f}x'}), use_container_width=True)

        st.write("**Campaign Performance** (Filtered View)")
        cp_tab = f_df.groupby(['channel', 'campaign']).agg({'spend':'sum', 'sales':'sum'}).reset_index()
        cp_tab['ROAS'] = cp_tab['sales'] / cp_tab['spend']
        st.dataframe(cp_tab.sort_values('spend', ascending=False).style.format({
            'spend':'₹{:,.2f}', 'sales':'₹{:,.2f}', 'ROAS':'{:.2f}x'
        }), use_container_width=True, hide_index=True)
