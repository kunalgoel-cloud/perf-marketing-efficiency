import streamlit as st
import pandas as pd
from supabase import create_client, Client
import io
import plotly.graph_objects as go
from datetime import datetime

# --- 1. CONFIG & DB CONNECTION ---
st.set_page_config(page_title="Performance Marketing Dashboard", layout="wide")

try:
    # Pulling from the new secrets you just added
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception:
    st.error("Missing Supabase Secrets! Add SUPABASE_URL and SUPABASE_KEY.")
    st.stop()

# --- 2. AUTHENTICATION ---
if "authenticated" not in st.session_state:
    st.title("🛡️ Marketing Efficiency Portal")
    u = st.text_input("User")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state["authenticated"] = True
            st.session_state["role"] = u
            st.rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

role = st.session_state["role"]

# --- 3. HELPER FUNCTIONS ---
def get_table_data(table_name):
    try:
        res = supabase.table(table_name).select("*").execute()
        return pd.DataFrame(res.data)
    except Exception as e:
        return pd.DataFrame()

def robust_read_file(file):
    if file.name.lower().endswith(('.xlsx', '.xls')):
        return pd.read_excel(file)
    return pd.read_csv(file)

def standardize_data(df):
    # Standardizing column names
    mapping = {
        'METRICS_DATE': 'date', 'TOTAL_SPEND': 'spend', 
        'TOTAL_GMV': 'sales', 'Date': 'date', 
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales'
    }
    df = df.rename(columns=mapping)
    
    # Cleaning numeric columns
    for col in ['spend', 'sales']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    # Formatting date
    df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
    return df.dropna(subset=['date'])

# --- 4. NAVIGATION ---
choice = st.sidebar.selectbox("Menu", ["Dashboard", "Upload Reports", "Settings"] if role == "admin" else ["Dashboard"])

# --- 5. SETTINGS ---
if choice == "Settings":
    st.header("⚙️ System Configuration")
    t1, t2 = st.tabs(["Master Data", "Campaign Mappings"])
    
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Channels")
            n_ch = st.text_input("New Channel")
            if st.button("Add Channel") and n_ch:
                supabase.table("channels").insert({"name": n_ch.strip()}).execute()
                st.rerun()
            st.dataframe(get_table_data("channels"), hide_index=True)
        with c2:
            st.subheader("Products")
            n_pr = st.text_input("New Product")
            if st.button("Add Product") and n_pr:
                supabase.table("products").insert({"name": n_pr.strip()}).execute()
                st.rerun()
            st.dataframe(get_table_data("products"), hide_index=True)

# --- 6. UPLOAD REPORTS ---
elif choice == "Upload Reports":
    st.header("📥 Ingest Marketing Data")
    ch_df = get_table_data("channels")
    if ch_df.empty:
        st.warning("Please add channels in Settings first.")
    else:
        sel_ch = st.selectbox("Select Channel for this file", ch_df['name'].tolist())
        file = st.file_uploader("Upload CSV or Excel", type=['csv', 'xlsx'])
        
        if file:
            df = standardize_data(robust_read_file(file))
            if st.button("🚀 Push to Supabase"):
                data_list = []
                for _, row in df.iterrows():
                    data_list.append({
                        "date": row['date'].strftime('%Y-%m-%d'),
                        "channel": sel_ch,
                        "campaign": row.get('campaign', 'Direct'),
                        "spend": float(row['spend']),
                        "sales": float(row['sales']),
                        "product": "Global" # Simplified for first run
                    })
                # Upsert handles potential duplicates automatically
                supabase.table("performance").upsert(data_list).execute()
                st.success(f"Successfully synced {len(data_list)} rows!")

# --- 7. DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Performance Dashboard")
    perf_df = get_table_data("performance")
    
    if not perf_df.empty:
        perf_df['date'] = pd.to_datetime(perf_df['date'])
        
        # Summary Row
        s1, s2, s3 = st.columns(3)
        total_spend = perf_df['spend'].sum()
        total_sales = perf_df['sales'].sum()
        s1.metric("Total Spend", f"₹{total_spend:,.0f}")
        s2.metric("Total Sales", f"₹{total_sales:,.0f}")
        s3.metric("ROAS", f"{(total_sales/total_spend):.2f}x" if total_spend > 0 else "0.00x")
        
        # Trend Chart
        daily = perf_df.groupby('date')[['spend', 'sales']].sum().reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=daily['date'], y=daily['spend'], name="Spend", line=dict(color='red')))
        fig.add_trace(go.Scatter(x=daily['date'], y=daily['sales'], name="Sales", line=dict(color='green')))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data available. Go to 'Upload Reports' to start.")
