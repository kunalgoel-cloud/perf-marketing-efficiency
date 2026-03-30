import streamlit as st
import pandas as pd
import io
import plotly.graph_objects as go
from datetime import datetime
from supabase import create_client, Client
import hashlib

st.set_page_config(page_title="Marketing Dashboard", page_icon="📊", layout="wide")

# --- CRITICAL FIX: Disable ALL Streamlit caching ---
# This ensures fresh data on every page load

def get_supabase_client() -> Client:
    """Initialize Supabase client"""
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"⚠️ Supabase connection error: {str(e)}")
        st.stop()

# Initialize fresh Supabase client every time
supabase = get_supabase_client()

# --- DATABASE HELPER FUNCTIONS (NO CACHING) ---
def get_all_products():
    """Get all products - NO CACHE"""
    try:
        response = supabase.table('products').select('name').order('name').execute()
        return [item['name'] for item in response.data]
    except:
        return []

def get_all_channels():
    """Get all channels - NO CACHE"""
    try:
        response = supabase.table('channels').select('name').order('name').execute()
        return [item['name'] for item in response.data]
    except:
        return []

def add_product(name):
    """Add a new product"""
    try:
        supabase.table('products').insert({'name': name}).execute()
        return True
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return False

def add_channel(name):
    """Add a new channel"""
    try:
        supabase.table('channels').insert({'name': name}).execute()
        return True
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return False

def get_all_mappings():
    """Get all mappings - NO CACHE"""
    try:
        response = supabase.table('mappings').select('campaign, product_name').order('campaign').execute()
        return pd.DataFrame(response.data)
    except:
        return pd.DataFrame(columns=['campaign', 'product_name'])

def add_mapping(campaign, product_name):
    """Add mapping"""
    try:
        supabase.table('mappings').insert({
            'campaign': campaign,
            'product_name': product_name
        }).execute()
        return True
    except:
        return False

def delete_mapping(campaign, product_name):
    """Delete mapping"""
    try:
        supabase.table('mappings').delete().eq('campaign', campaign).eq('product_name', product_name).execute()
        return True
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return False

def get_all_performance():
    """Get all performance data - ALWAYS FRESH, NO CACHE"""
    try:
        # Force fresh fetch every single time
        response = supabase.table('performance').select('*').order('date', desc=True).execute()
        df = pd.DataFrame(response.data)
        
        # Log fetch for debugging
        if not df.empty:
            st.session_state.last_fetch_time = datetime.now()
            st.session_state.last_fetch_count = len(df)
            st.session_state.last_fetch_dates = f"{df['date'].min()} to {df['date'].max()}"
        
        return df
    except Exception as e:
        st.error(f"Error fetching performance data: {str(e)}")
        return pd.DataFrame()

def add_performance_record(date, channel, campaign, product, spend, sales):
    """Add or update performance record"""
    try:
        record = {
            'date': date,
            'channel': channel,
            'campaign': campaign,
            'product': product,
            'spend': float(spend),
            'sales': float(sales),
            'clicks': 0,
            'orders': 0
        }
        
        supabase.table('performance').upsert(
            record,
            on_conflict='date,channel,campaign,product'
        ).execute()
        
        return True
    except Exception as e:
        try:
            existing = supabase.table('performance').select('*').eq('date', date).eq('channel', channel).eq('campaign', campaign).eq('product', product).execute()
            
            if existing.data and len(existing.data) > 0:
                supabase.table('performance').update({
                    'spend': float(spend),
                    'sales': float(sales)
                }).eq('date', date).eq('channel', channel).eq('campaign', campaign).eq('product', product).execute()
            else:
                supabase.table('performance').insert(record).execute()
            
            return True
        except Exception as e2:
            st.error(f"Error saving: {str(e2)}")
            return False

def delete_performance_records(channel, date):
    """Delete performance records"""
    try:
        result = supabase.table('performance').delete().eq('channel', channel).eq('date', date).execute()
        return len(result.data) if result.data else 0
    except Exception as e:
        st.error(f"Error deleting: {str(e)}")
        return 0

# --- DATA PROCESSING ---
def robust_read_file(file):
    """Read CSV or Excel files"""
    file_name = file.name.lower()
    if file_name.endswith(('.xlsx', '.xls')):
        try:
            return pd.read_excel(file)
        except Exception as e:
            st.error(f"Error reading Excel: {str(e)}")
            return None
    
    bytes_data = file.read()
    for enc in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            df_check = pd.read_csv(io.BytesIO(bytes_data), encoding=enc, nrows=10)
            if 'METRICS_DATE' not in df_check.columns and any("Selected Filters" in str(col) for col in df_check.columns):
                return pd.read_csv(io.BytesIO(bytes_data), encoding=enc, skiprows=6)
            return pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
        except: 
            continue
    
    st.error("Could not read file")
    return None

def standardize_data(df, manual_date=None):
    """Standardize data"""
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'Campaign name': 'campaign', 
        'Total cost': 'spend', 'Sales': 'sales', 
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales'
    }
    df = df.rename(columns=mapping)
    
    if 'campaign' not in df.columns: 
        df['campaign'] = "CHANNEL_TOTAL"
    
    for col in ['spend', 'sales']:
        if col not in df.columns: 
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    df = df[df['spend'] > 0].copy()
    
    if manual_date:
        df['date'] = manual_date.strftime('%Y-%m-%d')
    else:
        df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['date'])
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    
    return df[['date', 'campaign', 'spend', 'sales']]

# --- AUTHENTICATION ---
if 'auth' not in st.session_state: 
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ Secure Marketing Portal")
    st.info("💡 admin/admin123 or viewer/view123")
    
    col1, col2 = st.columns(2)
    with col1:
        u = st.text_input("Username")
    with col2:
        p = st.text_input("Password", type="password")
    
    if st.button("Login", type="primary"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.auth = True
            st.session_state.role = u
            st.success("✅ Login successful!")
            st.rerun()
        else:
            st.error("❌ Invalid credentials")
    st.stop()

# Navigation
choice = st.sidebar.selectbox(
    "Navigation", 
    ["Dashboard", "Upload Reports", "Settings", "Data History"] if st.session_state.role == "admin" else ["Dashboard", "Data History"]
)

# --- SETTINGS ---
if choice == "Settings":
    st.header("⚙️ System Management")
    t1, t2, t3 = st.tabs(["Master Data", "Mapping Manager", "Data Cleanup"])
    
    with t1:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📢 Channels")
            new_ch = st.text_input("Add Channel")
            if st.button("Save Channel"): 
                if new_ch:
                    if add_channel(new_ch):
                        st.success(f"✅ '{new_ch}' added!")
                        st.rerun()
                else:
                    st.warning("Enter a channel name")
            
            channels = get_all_channels()
            if channels:
                st.dataframe(pd.DataFrame({'name': channels}), hide_index=True, use_container_width=True, height=300)
                st.caption(f"Total: {len(channels)}")
            else:
                st.info("No channels")
        
        with col2:
            st.subheader("📦 Products")
            new_pr = st.text_input("Add Product")
            if st.button("Save Product"): 
                if new_pr:
                    if add_product(new_pr):
                        st.success(f"✅ '{new_pr}' added!")
                        st.rerun()
                else:
                    st.warning("Enter a product name")
            
            products = get_all_products()
            if products:
                st.dataframe(pd.DataFrame({'name': products}), hide_index=True, use_container_width=True, height=300)
                st.caption(f"Total: {len(products)}")
            else:
                st.info("No products")
    
    with t2:
        st.subheader("🔗 Mapping Manager")
        df_map = get_all_mappings()
        
        if not df_map.empty:
            st.caption(f"Total: {len(df_map)}")
            search = st.text_input("🔍 Search")
            
            if search: 
                df_map = df_map[df_map['campaign'].str.contains(search, case=False, na=False)]
            
            for idx, row in df_map.iterrows():
                m_col1, m_col2 = st.columns([3, 1])
                m_col1.write(f"**{row['campaign']}** → {row['product_name']}")
                if m_col2.button("Delete", key=f"del_{idx}"):
                    if delete_mapping(row['campaign'], row['product_name']):
                        st.success("✅ Deleted!")
                        st.rerun()
        else:
            st.info("No mappings")
    
    with t3:
        st.subheader("🗑️ Delete Data")
        st.warning("⚠️ Caution!")
        
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            channels = get_all_channels()
            target_ch = st.selectbox("Channel", ["Select"] + channels)
        with d_col2:
            target_date = st.date_input("Date", value=None)
        
        if st.button("Delete Records", type="primary"):
            if target_ch != "Select" and target_date:
                d_str = target_date.strftime('%Y-%m-%d')
                deleted = delete_performance_records(target_ch, d_str)
                st.warning(f"✅ Deleted {deleted} records")
                if deleted > 0:
                    st.rerun()
            else:
                st.error("Select channel and date")

# --- UPLOAD ---
elif choice == "Upload Reports":
    st.header("📥 Data Ingestion")
    
    channels = get_all_channels()
    products = get_all_products()
    
    if not channels or not products:
        st.warning("⚠️ Configure Channels and Products first!")
        st.stop()
    
    u_col1, u_col2 = st.columns(2)
    with u_col1: 
        manual_date = st.date_input("Date Override", value=None)
    with u_col2:
        sel_ch = st.selectbox("Channel", channels)
    
    file = st.file_uploader("Upload File", type=['csv', 'xlsx'])
    
    if file:
        with st.spinner("Processing..."):
            raw_df = robust_read_file(file)
            
            if raw_df is not None:
                df = standardize_data(raw_df, manual_date=manual_date)
                
                st.success(f"✅ Processed {len(df)} rows")
                st.dataframe(df.head(10), use_container_width=True)
                
                df_map = get_all_mappings()
                mappings = {}
                if not df_map.empty:
                    for _, row in df_map.iterrows():
                        if row['campaign'] not in mappings:
                            mappings[row['campaign']] = []
                        mappings[row['campaign']].append(row['product_name'])
                
                unmapped = [cp for cp in df['campaign'].unique() if cp not in mappings]
                
                if unmapped:
                    st.warning(f"⚠️ {len(unmapped)} campaigns need mapping")
                    prods = products + ["Brand/Global"]
                    
                    with st.form("map_form"):
                        st.subheader("Map Campaigns")
                        new_maps = {}
                        for cp in unmapped:
                            new_maps[cp] = st.multiselect(f"**{cp}**", prods, key=f"map_{cp}")
                        
                        if st.form_submit_button("💾 Save Mappings", type="primary"):
                            success_count = 0
                            for cp, pl in new_maps.items():
                                if pl:
                                    for pn in pl: 
                                        if add_mapping(cp, pn):
                                            success_count += 1
                            if success_count > 0:
                                st.success(f"✅ {success_count} saved!")
                                st.rerun()
                else:
                    st.success("✅ All mapped!")
                    
                    if st.button("🚀 Push to Dashboard", type="primary"):
                        with st.spinner("Uploading..."):
                            inserted = 0
                            errors = 0
                            
                            for _, row in df.iterrows():
                                targets = mappings.get(row['campaign'], ["Unmapped"])
                                n = len(targets)
                                
                                for p_name in targets:
                                    if add_performance_record(
                                        row['date'], sel_ch, row['campaign'], p_name,
                                        float(row['spend']/n), float(row['sales']/n)
                                    ):
                                        inserted += 1
                                    else:
                                        errors += 1
                            
                            if inserted > 0:
                                st.success(f"✅ Pushed {inserted} records!")
                                if errors > 0:
                                    st.warning(f"⚠️ {errors} errors")
                                
                                # Force complete page reload to clear all caches
                                st.balloons()
                                st.info("✅ Upload complete! Click Dashboard to view.")
                            else:
                                st.error("❌ No records uploaded")
            else:
                st.error("❌ Could not process file")

# --- DATA HISTORY ---
elif choice == "Data History":
    st.header("📚 Data History")
    
    # CRITICAL: Always fetch fresh data
    df_p = get_all_performance()
    
    if df_p.empty:
        st.info("No data")
    else:
        df_p = df_p.drop(columns=['id', 'created_at'], errors='ignore')
        df_p['date'] = pd.to_datetime(df_p['date'])
        
        st.subheader("📊 Summary")
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Total Records", f"{len(df_p):,}")
        with col2:
            st.metric("Date Range", f"{df_p['date'].min().strftime('%Y-%m-%d')} to {df_p['date'].max().strftime('%Y-%m-%d')}")
        with col3:
            st.metric("Channels", df_p['channel'].nunique())
        with col4:
            st.metric("Products", df_p['product'].nunique())
        
        st.divider()
        
        st.subheader("History")
        history = df_p.groupby(['date', 'channel']).agg({
            'campaign': 'count',
            'spend': 'sum',
            'sales': 'sum'
        }).reset_index()
        history.columns = ['Date', 'Channel', 'Records', 'Spend', 'Sales']
        history = history.sort_values('Date', ascending=False)
        
        st.dataframe(
            history.style.format({
                'Spend': '₹{:,.2f}',
                'Sales': '₹{:,.2f}'
            }),
            use_container_width=True,
            hide_index=True
        )

# --- DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Performance Dashboard")
    
    # CRITICAL FIX: Always fetch fresh data, NEVER use cache
    df_p = get_all_performance()
    
    # Debug info
    st.sidebar.divider()
    st.sidebar.caption("🔍 Debug Info")
    if 'last_fetch_time' in st.session_state:
        st.sidebar.caption(f"Fetched: {st.session_state.last_fetch_time.strftime('%H:%M:%S')}")
        st.sidebar.caption(f"Records: {st.session_state.last_fetch_count:,}")
        st.sidebar.caption(f"Dates: {st.session_state.last_fetch_dates}")
    
    if df_p.empty: 
        st.info("📭 No data. Please upload in 'Upload Reports'.")
        st.stop()
    
    df_p = df_p.drop(columns=['id', 'created_at'], errors='ignore')
    df_p['date'] = pd.to_datetime(df_p['date'])
    
    # Sidebar Filters
    st.sidebar.subheader("🎯 Filters")
    
    # Force refresh button
    if st.sidebar.button("🔄 Refresh Data", type="primary"):
        st.rerun()
    
    st.sidebar.divider()
    
    # Date range
    min_date = df_p['date'].min().date()
    max_date = df_p['date'].max().date()
    
    st.sidebar.success(f"📅 Available: {min_date} to {max_date}")
    
    dr = st.sidebar.date_input(
        "Date Range", 
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )
    
    # Channel filter
    all_channels = sorted(df_p['channel'].unique().tolist())
    ch_f = st.sidebar.multiselect(
        "Channels", 
        all_channels, 
        default=all_channels
    )
    
    # Product filter
    all_products = sorted(df_p['product'].unique().tolist())
    pr_f = st.sidebar.multiselect(
        "Products", 
        all_products, 
        default=all_products
    )
    
    # Apply filters
    if len(dr) == 2:
        f_df = df_p[
            (df_p['date'] >= pd.to_datetime(dr[0])) & 
            (df_p['date'] <= pd.to_datetime(dr[1])) & 
            (df_p['channel'].isin(ch_f)) & 
            (df_p['product'].isin(pr_f))
        ]
    else: 
        f_df = df_p[
            (df_p['channel'].isin(ch_f)) & 
            (df_p['product'].isin(pr_f))
        ]
    
    if f_df.empty:
        st.warning("No data matches filters")
        st.stop()
    
    # Key Metrics
    t_spend, t_sales = f_df['spend'].sum(), f_df['sales'].sum()
    roas = t_sales / t_spend if t_spend > 0 else 0
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Spend", f"₹{t_spend:,.0f}")
    k2.metric("Total Revenue", f"₹{t_sales:,.0f}")
    k3.metric("Overall ROAS", f"{roas:.2f}x")
    
    st.divider()
    
    # Chart
    st.subheader("📈 Efficiency Trend by Channel")
    
    ch_trend = f_df.groupby(['date', 'channel']).agg({'spend':'sum', 'sales':'sum'}).reset_index()
    ch_trend['ROAS'] = ch_trend['sales'] / ch_trend['spend']
    total_trend = f_df.groupby('date').agg({'spend':'sum', 'sales':'sum'}).reset_index()
    total_trend['ROAS'] = total_trend['sales'] / total_trend['spend']
    
    fig = go.Figure()
    
    for channel in sorted(ch_trend['channel'].unique()):
        ch_data = ch_trend[ch_trend['channel'] == channel]
        fig.add_trace(go.Bar(
            x=ch_data['date'], 
            y=ch_data['spend'], 
            name=f"{channel} Spend"
        ))
    
    for channel in sorted(ch_trend['channel'].unique()):
        ch_data = ch_trend[ch_trend['channel'] == channel]
        fig.add_trace(go.Scatter(
            x=ch_data['date'], 
            y=ch_data['ROAS'], 
            name=f"{channel} ROAS", 
            yaxis="y2", 
            mode='lines+markers'
        ))
    
    fig.add_trace(go.Scatter(
        x=total_trend['date'], 
        y=total_trend['ROAS'], 
        name="Total ROAS", 
        yaxis="y2", 
        line=dict(color='black', width=4, dash='dot')
    ))
    
    fig.update_layout(
        barmode='stack',
        yaxis=dict(title="Spend (₹)"),
        yaxis2=dict(
            title="ROAS", 
            overlaying="y", 
            side="right", 
            range=[0, ch_trend['ROAS'].max()*1.2 if not ch_trend.empty else 10]
        ),
        legend=dict(orientation="h", y=1.2),
        hovermode="x unified",
        height=500
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # Tables
    c1, c2 = st.columns(2)
    with c1:
        st.write("**By Channel**")
        channel_summary = f_df.groupby('channel').agg({
            'spend':'sum', 
            'sales':'sum'
        }).assign(ROAS=lambda x: x.sales/x.spend).sort_values('spend', ascending=False)
        
        st.dataframe(
            channel_summary.style.format({
                'spend': '₹{:,.2f}',
                'sales': '₹{:,.2f}',
                'ROAS': '{:.2f}x'
            }), 
            use_container_width=True
        )
    
    with c2:
        st.write("**By Product**")
        product_summary = f_df.groupby('product').agg({
            'spend':'sum', 
            'sales':'sum'
        }).assign(ROAS=lambda x: x.sales/x.spend).sort_values('spend', ascending=False)
        
        st.dataframe(
            product_summary.style.format({
                'spend': '₹{:,.2f}',
                'sales': '₹{:,.2f}',
                'ROAS': '{:.2f}x'
            }), 
            use_container_width=True
        )
    
    st.divider()
    
    st.write("**Campaign Performance**")
    cp_tab = f_df.groupby(['channel', 'campaign']).agg({
        'spend':'sum', 
        'sales':'sum'
    }).assign(ROAS=lambda x: x.sales/x.spend).reset_index()
    
    st.dataframe(
        cp_tab.sort_values('spend', ascending=False).style.format({
            'spend':'₹{:,.2f}', 
            'sales':'₹{:,.2f}', 
            'ROAS':'{:.2f}x'
        }), 
        use_container_width=True, 
        hide_index=True,
        height=300
    )
    
    # Detailed table
    st.divider()
    st.subheader("📅 Detailed Date-wise Performance")
    
    detail_tab = f_df[['date', 'channel', 'product', 'campaign', 'spend', 'sales']].copy()
    detail_tab['ROAS'] = detail_tab['sales'] / detail_tab['spend']
    detail_tab['date'] = detail_tab['date'].dt.strftime('%Y-%m-%d')
    
    detail_tab = detail_tab.rename(columns={
        'date': 'Date',
        'channel': 'Channel',
        'product': 'Product',
        'campaign': 'Campaign',
        'spend': 'Marketing Spend (₹)',
        'sales': 'Ad Revenue (₹)',
        'ROAS': 'ROAS'
    })
    detail_tab = detail_tab.sort_values('Date', ascending=False)
    
    st.dataframe(
        detail_tab.style.format({
            'Marketing Spend (₹)': '₹{:,.2f}',
            'Ad Revenue (₹)': '₹{:,.2f}',
            'ROAS': '{:.2f}x'
        }),
        use_container_width=True,
        hide_index=True,
        height=400
    )
    
    st.caption(f"Total Records: {len(detail_tab):,}")
    
    # Downloads
    col_d1, col_d2, col_d3 = st.columns(3)
    
    with col_d1:
        csv_data = detail_tab.to_csv(index=False)
        st.download_button(
            label="📥 CSV",
            data=csv_data,
            file_name=f"performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col_d2:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            detail_tab.to_excel(writer, index=False, sheet_name='Performance')
            
            summary_data = pd.DataFrame({
                'Metric': ['Spend', 'Revenue', 'ROAS', 'Date Range', 'Records'],
                'Value': [
                    f"₹{t_spend:,.2f}",
                    f"₹{t_sales:,.2f}",
                    f"{roas:.2f}x",
                    f"{dr[0]} to {dr[1]}" if len(dr) == 2 else "All",
                    f"{len(detail_tab):,}"
                ]
            })
            summary_data.to_excel(writer, index=False, sheet_name='Summary')
        
        excel_data = excel_buffer.getvalue()
        st.download_button(
            label="📥 Excel",
            data=excel_data,
            file_name=f"performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlsheet",
            use_container_width=True
        )
    
    with col_d3:
        summary_csv = pd.concat([
            channel_summary.reset_index().assign(Group='Channel'),
            product_summary.reset_index().assign(Group='Product')
        ])
        
        st.download_button(
            label="📥 Summary",
            data=summary_csv.to_csv(index=False),
            file_name=f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# Footer
st.sidebar.divider()
st.sidebar.caption(f"👤 {st.session_state.role}")
if st.sidebar.button("🚪 Logout"):
    st.session_state.auth = False
    st.rerun()

st.sidebar.divider()
st.sidebar.success("☁️ Connected to Supabase")
st.sidebar.caption(f"🕐 {datetime.now().strftime('%H:%M:%S')}")
