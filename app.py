import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go
from datetime import datetime

# --- 1. DATABASE SETUP ---
# v10 ensures a fresh schema for multi-product splitting and deletion logic
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
            # Detect Swiggy/Instamart reports that have 6 lines of metadata
            df_check = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, nrows=10)
            if 'METRICS_DATE' not in df_check.columns and any("Selected Filters" in str(col) for col in df_check.columns):
                 return pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: continue
    return None

def standardize_data(df, manual_date=None):
    # Mapping for Swiggy, Amazon, and Generic Summaries
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'TOTAL_CLICKS': 'clicks', 'TOTAL_CONVERSIONS': 'orders',
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 
        'Campaign start date': 'date', 'Clicks': 'clicks', 'Purchases': 'orders',
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales', 'Ad Clicks': 'clicks', 'Orders (SKU)': 'orders'
    }
    df = df.rename(columns=mapping)
    
    # Numeric Clean-up (Handles currency symbols and commas)
    for col in ['spend', 'sales', 'clicks', 'orders']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)

    # REQ: Filter out campaigns with zero spend
    df = df[df['spend'] > 0].copy()

    # DATE LOGIC: Manual Override > File Date
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

# --- 4. NAVIGATION ---
choice = st.sidebar.selectbox("Navigation", ["Dashboard", "Upload Reports", "Settings"] if st.session_state.role == "admin" else ["Dashboard"])

# --- 5. SETTINGS: MASTER DATA & DELETION ---
if choice == "Settings":
    st.header("⚙️ Settings & Data Management")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Manage Channels")
        new_ch = st.text_input("New Channel (e.g. Swiggy)")
        if st.button("Add Channel"): 
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name FROM channels", conn), hide_index=True)
    with col2:
        st.subheader("Manage Products")
        new_pr = st.text_input("New Product (e.g. Patal Poha)")
        if st.button("Add Product"): 
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
            conn.commit()
        st.dataframe(pd.read_sql("SELECT name FROM products", conn), hide_index=True)

    st.divider()
    st.subheader("🗑️ Delete Data by Channel/Date")
    st.info("Use this to clear incorrect uploads.")
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
            st.warning(f"Cleared all {target_ch} data for {d_str}")
        else:
            st.error("Select both Channel and Date")

# --- 6. UPLOAD: PROCESSING & MAPPING ---
elif choice == "Upload Reports":
    st.header("📥 Upload Ad Reports")
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
            
            # Fetch mappings to check for unmapped campaigns
            mappings = {}
            for r in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
                mappings.setdefault(r[0], []).append(r[1])
            
            unmapped = [cp for cp in df['campaign'].unique() if cp not in mappings]
            
            if unmapped:
                st.warning(f"Found {len(unmapped)} new campaigns. Map them to products.")
                prods = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                with st.form("map_form"):
                    new_maps = {}
                    for cp in unmapped:
                        new_maps[cp] = st.multiselect(f"Products for: {cp}", prods)
                    if st.form_submit_button("Save Mappings"):
                        for cp, p_list in new_maps.items():
                            for p_name in p_list:
                                c.execute("INSERT OR IGNORE INTO mappings VALUES (?,?)", (cp, p_name))
                        conn.commit()
                        st.rerun()
            else:
                if st.button("Save Data to Dashboard"):
                    for _, row in df.iterrows():
                        target_prods = mappings.get(row['campaign'], ["Unmapped"])
                        n = len(target_prods)
                        for p_name in target_prods:
                            c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", 
                                      (row['date'], sel_ch, row['campaign'], p_name, row['spend']/n, row['sales']/n, row['clicks']/n, row['orders']/n))
                    conn.commit()
                    st.success("Successfully pushed to Dashboard!")

# --- 7. DASHBOARD: ANALYTICS & TABLES ---
elif choice == "Dashboard":
    st.header("📊 Performance Analytics")
    df_p = pd.read_sql("SELECT * FROM performance", conn)
    if df_p.empty:
        st.info("No data found. Start by uploading reports.")
    else:
        st.sidebar.subheader("Global Filters")
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

        # Tabular Views
        st.divider()
        st.subheader("📈 Performance Deep Dive")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**By Channel**")
            ch_tab = f_df.groupby('channel').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False)
            st.dataframe(ch_tab.style.format({'spend':'₹{:,.0f}', 'sales':'₹{:,.0f}', 'ROAS':'{:.2f}x'}), use_container_width=True)
        with c2:
            st.write("**By Product**")
            pr_tab = f_df.groupby('product').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).sort_values('ROAS', ascending=False)
            st.dataframe(pr_tab.style.format({'spend':'₹{:,.0f}', 'sales':'₹{:,.0f}', 'ROAS':'{:.2f}x'}), use_container_width=True)

        st.write("**By Individual Campaign**")
        cp_tab = f_df.groupby(['channel', 'campaign']).agg({'spend':'sum', 'sales':'sum', 'clicks':'sum', 'orders':'sum'}).reset_index()
        cp_tab['ROAS'] = cp_tab['sales'] / cp_tab['spend']
        cp_tab['CPC'] = cp_tab['spend'] / cp_tab['clicks']
        st.dataframe(cp_tab.sort_values('spend', ascending=False).style.format({
            'spend':'₹{:,.2f}', 'sales':'₹{:,.2f}', 'ROAS':'{:.2f}x', 'CPC':'₹{:,.2f}'
        }), use_container_width=True, hide_index=True)
