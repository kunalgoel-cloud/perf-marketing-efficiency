import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import io
import plotly.graph_objects as go
from datetime import datetime

# --- 1. DATABASE SETUP (DIRECT CONNECTION) ---
try:
    # Pulling the URL from Streamlit Secrets
    DB_URL = st.secrets["SUPABASE_DB_URL"]
    
    # Setup the engine with stability settings
    engine = create_engine(
        DB_URL,
        connect_args={"sslmode": "require", "connect_timeout": 10},
        pool_pre_ping=True,
        pool_recycle=300
    )
except Exception as e:
    st.error("Database connection failed. Please verify your Streamlit Secrets.")
    st.stop()

# --- 2. DATA PROCESSING ENGINE ---
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

# --- 3. AUTHENTICATION ---
if 'auth' not in st.session_state: st.session_state.auth = False
if not st.session_state.auth:
    st.title("🛡️ Secure Marketing Portal")
    u, p = st.text_input("User"), st.text_input("Password", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth, st.session_state.role = True, u
            st.rerun()
    st.stop()

choice = st.sidebar.selectbox("Navigation", ["Dashboard", "Upload Reports", "Settings"] if st.session_state.role == "admin" else ["Dashboard"])

# --- 4. SETTINGS ---
if choice == "Settings":
    st.header("⚙️ System Management")
    t1, t2 = st.tabs(["Master Data", "Mapping Manager"])
    
    with t1:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Channels")
            new_ch = st.text_input("Add Channel")
            if st.button("Save Channel"): 
                with engine.connect() as conn:
                    conn.execute(text("INSERT INTO channels (name) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": new_ch})
                    conn.commit()
                st.rerun()
            st.dataframe(pd.read_sql("SELECT name FROM channels", engine), hide_index=True)
        with col2:
            st.subheader("Products")
            new_pr = st.text_input("Add Product")
            if st.button("Save Product"): 
                with engine.connect() as conn:
                    conn.execute(text("INSERT INTO products (name) VALUES (:name) ON CONFLICT DO NOTHING"), {"name": new_pr})
                    conn.commit()
                st.rerun()
            st.dataframe(pd.read_sql("SELECT name FROM products", engine), hide_index=True)

    with t2:
        st.subheader("🔗 Mapping Manager")
        df_map = pd.read_sql("SELECT campaign, product_name FROM mappings", engine)
        for _, row in df_map.iterrows():
            m_col1, m_col2 = st.columns([3, 1])
            m_col1.write(f"**{row['campaign']}** → {row['product_name']}")
            if m_col2.button("Delete", key=f"del_{row['campaign']}_{row['product_name']}"):
                with engine.connect() as conn:
                    conn.execute(text("DELETE FROM mappings WHERE campaign=:c AND product_name=:p"), {"c": row['campaign'], "p": row['product_name']})
                    conn.commit()
                st.rerun()

# --- 5. UPLOAD ---
elif choice == "Upload Reports":
    st.header("📥 Data Ingestion")
    u_col1, u_col2 = st.columns(2)
    with u_col1: manual_date = st.date_input("Date Override (Optional)", value=None)
    with u_col2:
        chs_df = pd.read_sql("SELECT name FROM channels", engine)
        chs = chs_df['name'].tolist()
        sel_ch = st.selectbox("Assign Channel", chs if chs else ["Add Channels in Settings first"])
    
    file = st.file_uploader("Upload File", type=['csv', 'xlsx'])
    if file:
        raw_df = robust_read_file(file)
        if raw_df is not None:
            df = standardize_data(raw_df, manual_date=manual_date)
            df_m = pd.read_sql("SELECT * FROM mappings", engine)
            mappings = df_m.groupby('campaign')['product_name'].apply(list).to_dict()
            
            unmapped = [cp for cp in df['campaign'].unique() if cp not in mappings]
            if unmapped:
                st.warning(f"Map {len(unmapped)} campaigns")
                prods_df = pd.read_sql("SELECT name FROM products", engine)
                prods = prods_df['name'].tolist() + ["Brand/Global"]
                with st.form("map_form"):
                    new_maps = {cp: st.multiselect(f"Map: {cp}", prods) for cp in unmapped}
                    if st.form_submit_button("Save Mappings"):
                        with engine.connect() as conn:
                            for cp, p_list in new_maps.items():
                                for p_name in p_list:
                                    conn.execute(text("INSERT INTO mappings (campaign, product_name) VALUES (:c, :p) ON CONFLICT DO NOTHING"), {"c": cp, "p": p_name})
                            conn.commit()
                        st.rerun()
            else:
                if st.button("🚀 Push to Supabase"):
                    with engine.connect() as conn:
                        unique_dates = df['date'].dt.strftime('%Y-%m-%d').unique()
                        for d_val in unique_dates:
                            conn.execute(text("DELETE FROM performance WHERE channel=:ch AND date=:dt"), {"ch": sel_ch, "dt": d_val})
                        
                        for _, row in df.iterrows():
                            targets = mappings.get(row['campaign'], ["Unmapped"])
                            n = len(targets)
                            for p_name in targets:
                                conn.execute(text("INSERT INTO performance (date, channel, campaign, product, spend, sales) VALUES (:d, :c, :cp, :p, :s, :sl)"),
                                             {"d": row['date'], "c": sel_ch, "cp": row['campaign'], "p": p_name, "s": row['spend']/n, "sl": row['sales']/n})
                        conn.commit()
                    st.success("Cloud Sync Complete!")

# --- 6. DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Performance Dashboard")
    df_p = pd.read_sql("SELECT * FROM performance", engine)
    if df_p.empty:
        st.info("Dashboard is empty. Please upload data.")
    else:
        df_p['date'] = pd.to_datetime(df_p['date'])
        st.sidebar.subheader("Filters")
        dr = st.sidebar.date_input("Date Range", value=(df_p['date'].min().date(), df_p['date'].max().date()))
        ch_f = st.sidebar.multiselect("Channels", df_p['channel'].unique(), default=df_p['channel'].unique())
        pr_f = st.sidebar.multiselect("Products", df_p['product'].unique(), default=df_p['product'].unique())

        mask = (df_p['date'] >= pd.to_datetime(dr[0])) & (df_p['date'] <= pd.to_datetime(dr[1])) & (df_p['channel'].isin(ch_f)) & (df_p['product'].isin(pr_f))
        f_df = df_p[mask]
        
        # Summary Metrics
        t_spend, t_sales = f_df['spend'].sum(), f_df['sales'].sum()
        roas = t_sales / t_spend if t_spend > 0 else 0
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Spend", f"₹{t_spend:,.0f}")
        k2.metric("Total Revenue", f"₹{t_sales:,.0f}")
        k3.metric("Total ROAS", f"{roas:.2f}x")

        # Trend Visualization
        ch_trend = f_df.groupby(['date', 'channel']).agg({'spend':'sum', 'sales':'sum'}).reset_index()
        ch_trend['ROAS'] = ch_trend['sales'] / ch_trend['spend']
        
        fig = go.Figure()
        for channel in ch_trend['channel'].unique():
            ch_data = ch_trend[ch_trend['channel'] == channel]
            fig.add_trace(go.Bar(x=ch_data['date'], y=ch_data['spend'], name=f"{channel} Spend"))
            fig.add_trace(go.Scatter(x=ch_data['date'], y=ch_data['ROAS'], name=f"{channel} ROAS", yaxis="y2"))
            
        fig.update_layout(
            barmode='stack',
            yaxis=dict(title="Spend (₹)"),
            yaxis2=dict(title="ROAS", overlaying="y", side="right", range=[0, 15]),
            legend=dict(orientation="h", y=1.2),
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.write("**Channel Efficiency Summary**")
        st.dataframe(f_df.groupby('channel').agg({'spend':'sum', 'sales':'sum'}).assign(ROAS=lambda x: x.sales/x.spend).style.format('{:.2f}'), use_container_width=True)
