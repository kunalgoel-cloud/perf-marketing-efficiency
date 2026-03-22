import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go
from datetime import datetime
import os
from pathlib import Path

# --- 1. PERSISTENT DATABASE CONFIGURATION ---
# Use a persistent directory that survives restarts
# For Streamlit Cloud, we'll use the working directory
# For local development, create a data directory

def get_database_path():
    """Get the database path - ensures it's in a persistent location"""
    # Try to use a data directory if it exists, otherwise use current directory
    data_dir = Path("./data")
    if not data_dir.exists():
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except:
            # If we can't create data dir, use current directory
            return "marketing_v10_final.db"
    
    return str(data_dir / "marketing_v10_final.db")

DB_PATH = get_database_path()

# Store database path in session state to track it
if 'db_path' not in st.session_state:
    st.session_state.db_path = DB_PATH

def get_db_connection():
    """Create a database connection with proper settings"""
    conn = sqlite3.connect(
        st.session_state.db_path, 
        check_same_thread=False, 
        timeout=30.0,
        isolation_level=None  # Autocommit mode for immediate persistence
    )
    # Enable WAL mode for better concurrent access
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')  # Faster writes
    conn.execute('PRAGMA temp_store=MEMORY')  # Use memory for temp storage
    return conn

def init_database():
    """Initialize database tables - preserves existing data"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Create tables with IF NOT EXISTS
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        name TEXT UNIQUE PRIMARY KEY
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
        name TEXT UNIQUE PRIMARY KEY
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS mappings (
        campaign TEXT,
        product_name TEXT,
        UNIQUE(campaign, product_name)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS performance (
        date TEXT NOT NULL,
        channel TEXT NOT NULL,
        campaign TEXT NOT NULL,
        product TEXT NOT NULL,
        spend REAL DEFAULT 0,
        sales REAL DEFAULT 0,
        clicks REAL DEFAULT 0,
        orders REAL DEFAULT 0
    )''')
    
    # Create indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_performance_date ON performance(date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_performance_channel ON performance(channel)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_performance_product ON performance(product)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_performance_composite ON performance(date, channel, product)')
    
    conn.commit()
    conn.close()

# Initialize database
init_database()

# Create persistent connection using session state instead of cache
if 'db_conn' not in st.session_state:
    st.session_state.db_conn = get_db_connection()

conn = st.session_state.db_conn
c = conn.cursor()

# --- 2. BACKUP AND RESTORE FUNCTIONS ---
def create_backup():
    """Create a backup of the database"""
    try:
        backup_dir = Path("./backups")
        backup_dir.mkdir(exist_ok=True)
        
        backup_path = backup_dir / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        
        # Create backup connection
        backup_conn = sqlite3.connect(str(backup_path))
        
        # Copy database
        with backup_conn:
            conn.backup(backup_conn)
        
        backup_conn.close()
        return str(backup_path)
    except Exception as e:
        st.error(f"Backup failed: {str(e)}")
        return None

def export_all_data_to_csv():
    """Export all database tables to CSV for backup"""
    try:
        # Create export directory
        export_dir = Path("./exports")
        export_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Export each table
        tables = ['products', 'channels', 'mappings', 'performance']
        export_files = {}
        
        for table in tables:
            df = pd.read_sql(f"SELECT * FROM {table}", conn)
            filepath = export_dir / f"{table}_{timestamp}.csv"
            df.to_csv(filepath, index=False)
            export_files[table] = str(filepath)
        
        return export_files
    except Exception as e:
        st.error(f"Export failed: {str(e)}")
        return None

# --- 3. DATA PROCESSING ENGINE ---
def robust_read_file(file):
    """Read CSV or Excel files with multiple encoding attempts"""
    file_name = file.name.lower()
    if file_name.endswith(('.xlsx', '.xls')):
        try:
            return pd.read_excel(file)
        except Exception as e:
            st.error(f"Error reading Excel file: {str(e)}")
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
    
    st.error("Could not read file with any encoding")
    return None

def standardize_data(df, manual_date=None):
    """Standardize column names and data formats"""
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

# --- 4. AUTHENTICATION ---
if 'auth' not in st.session_state: 
    st.session_state.auth = False

if not st.session_state.auth:
    st.title("🛡️ Secure Marketing Portal")
    st.info("💡 Login to access the dashboard. Default credentials: admin/admin123 or viewer/view123")
    
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
    ["Dashboard", "Upload Reports", "Settings", "Data History", "Backup & Restore"] if st.session_state.role == "admin" else ["Dashboard", "Data History"]
)

# --- 5. SETTINGS ---
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
                    try:
                        c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
                        conn.commit()
                        st.success(f"✅ Channel '{new_ch}' added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                else:
                    st.warning("Please enter a channel name")
            
            channels_df = pd.read_sql("SELECT name FROM channels ORDER BY name", conn)
            st.dataframe(channels_df, hide_index=True, use_container_width=True, height=300)
            st.caption(f"Total Channels: {len(channels_df)}")
        
        with col2:
            st.subheader("📦 Products")
            new_pr = st.text_input("Add Product")
            if st.button("Save Product"): 
                if new_pr:
                    try:
                        c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
                        conn.commit()
                        st.success(f"✅ Product '{new_pr}' added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                else:
                    st.warning("Please enter a product name")
            
            products_df = pd.read_sql("SELECT name FROM products ORDER BY name", conn)
            st.dataframe(products_df, hide_index=True, use_container_width=True, height=300)
            st.caption(f"Total Products: {len(products_df)}")
    
    with t2:
        st.subheader("🔗 Mapping Manager")
        df_map = pd.read_sql("SELECT campaign, product_name FROM mappings ORDER BY campaign", conn)
        
        st.caption(f"Total Mappings: {len(df_map)}")
        search = st.text_input("🔍 Search Campaign")
        
        if search: 
            df_map = df_map[df_map['campaign'].str.contains(search, case=False, na=False)]
        
        if not df_map.empty:
            for idx, row in df_map.iterrows():
                m_col1, m_col2 = st.columns([3, 1])
                m_col1.write(f"**{row['campaign']}** → {row['product_name']}")
                if m_col2.button("Delete", key=f"del_{idx}"):
                    try:
                        c.execute("DELETE FROM mappings WHERE campaign=? AND product_name=?", 
                                (row['campaign'], row['product_name']))
                        conn.commit()
                        st.success("✅ Mapping deleted!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        else:
            st.info("No mappings found")
    
    with t3:
        st.subheader("🗑️ Delete Data")
        st.warning("⚠️ Use with caution - this will permanently delete data!")
        
        d_col1, d_col2 = st.columns(2)
        with d_col1:
            channels_list = [r[0] for r in c.execute("SELECT name FROM channels ORDER BY name").fetchall()]
            target_ch = st.selectbox("Channel", ["Select"] + channels_list)
        with d_col2:
            target_date = st.date_input("Date", value=None)
        
        if st.button("Delete Records", type="primary"):
            if target_ch != "Select" and target_date:
                d_str = target_date.strftime('%Y-%m-%d')
                try:
                    c.execute("DELETE FROM performance WHERE channel=? AND date=?", 
                            (target_ch, d_str))
                    deleted_count = c.rowcount
                    conn.commit()
                    st.warning(f"✅ Deleted {deleted_count} records for {target_ch} on {d_str}")
                except Exception as e:
                    st.error(f"Error: {str(e)}")
            else:
                st.error("Please select both channel and date")

# --- 6. BACKUP & RESTORE ---
elif choice == "Backup & Restore":
    st.header("💾 Backup & Restore")
    
    tab1, tab2 = st.tabs(["Create Backup", "Export Data"])
    
    with tab1:
        st.subheader("Create Database Backup")
        st.info("Create a backup copy of your entire database")
        
        if st.button("📦 Create Backup Now", type="primary"):
            with st.spinner("Creating backup..."):
                backup_path = create_backup()
                if backup_path:
                    st.success(f"✅ Backup created: {backup_path}")
                    
                    # Offer download
                    with open(backup_path, 'rb') as f:
                        st.download_button(
                            label="📥 Download Backup File",
                            data=f.read(),
                            file_name=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                            mime="application/x-sqlite3"
                        )
    
    with tab2:
        st.subheader("Export All Data to CSV")
        st.info("Export all tables to CSV format for external analysis or backup")
        
        if st.button("📊 Export All Tables", type="primary"):
            with st.spinner("Exporting data..."):
                export_files = export_all_data_to_csv()
                if export_files:
                    st.success("✅ Data exported successfully!")
                    
                    # Create a zip file with all exports
                    import zipfile
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        for table, filepath in export_files.items():
                            zip_file.write(filepath, os.path.basename(filepath))
                    
                    st.download_button(
                        label="📥 Download All Exports (ZIP)",
                        data=zip_buffer.getvalue(),
                        file_name=f"data_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                        mime="application/zip"
                    )

# --- 7. UPLOAD ---
elif choice == "Upload Reports":
    st.header("📥 Data Ingestion")
    
    # Check if we have master data
    channels_count = c.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    products_count = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    
    if channels_count == 0 or products_count == 0:
        st.warning("⚠️ Please configure Channels and Products in Settings first!")
        if st.button("Go to Settings"):
            st.rerun()
        st.stop()
    
    u_col1, u_col2 = st.columns(2)
    with u_col1: 
        manual_date = st.date_input("Date Override (Optional)", value=None)
    with u_col2:
        channels_list = [r[0] for r in c.execute("SELECT name FROM channels ORDER BY name").fetchall()]
        sel_ch = st.selectbox("Assign Channel", channels_list)
    
    file = st.file_uploader("Upload File", type=['csv', 'xlsx'])
    
    if file:
        with st.spinner("Processing file..."):
            raw_df = robust_read_file(file)
            
            if raw_df is not None:
                df = standardize_data(raw_df, manual_date=manual_date)
                
                st.success(f"✅ Processed {len(df)} rows")
                st.dataframe(df.head(10), use_container_width=True)
                
                # Get existing mappings
                mappings = {}
                for r in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
                    mappings.setdefault(r[0], []).append(r[1])
                
                unmapped = [cp for cp in df['campaign'].unique() if cp not in mappings]
                
                if unmapped:
                    st.warning(f"⚠️ {len(unmapped)} campaigns need mapping")
                    prods = [r[0] for r in c.execute("SELECT name FROM products ORDER BY name").fetchall()] + ["Brand/Global"]
                    
                    with st.form("map_form"):
                        st.subheader("Map Campaigns to Products")
                        new_maps = {}
                        for cp in unmapped:
                            new_maps[cp] = st.multiselect(f"**{cp}**", prods, key=f"map_{cp}")
                        
                        if st.form_submit_button("💾 Save Mappings", type="primary"):
                            try:
                                for cp, pl in new_maps.items():
                                    if pl:
                                        for pn in pl: 
                                            c.execute("INSERT OR IGNORE INTO mappings VALUES (?,?)", (cp, pn))
                                conn.commit()
                                st.success("✅ Mappings saved!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {str(e)}")
                else:
                    st.success("✅ All campaigns are mapped!")
                    
                    if st.button("🚀 Push to Dashboard", type="primary"):
                        try:
                            inserted = 0
                            
                            for _, row in df.iterrows():
                                targets = mappings.get(row['campaign'], ["Unmapped"])
                                n = len(targets)
                                
                                for p_name in targets:
                                    c.execute("""
                                        INSERT OR REPLACE INTO performance 
                                        (date, channel, campaign, product, spend, sales, clicks, orders) 
                                        VALUES (?,?,?,?,?,?,?,?)
                                    """, (row['date'], sel_ch, row['campaign'], p_name, 
                                         row['spend']/n, row['sales']/n, 0, 0))
                                    inserted += 1
                            
                            conn.commit()
                            st.success(f"✅ Successfully pushed {inserted} records to dashboard!")
                            
                            # Auto-create backup after successful upload
                            with st.spinner("Creating automatic backup..."):
                                create_backup()
                                st.info("💾 Automatic backup created")
                            
                        except Exception as e:
                            st.error(f"Error: {str(e)}")
                            conn.rollback()
            else:
                st.error("❌ Could not process file")

# --- 8. DATA HISTORY ---
elif choice == "Data History":
    st.header("📚 Data Upload History")
    
    df_p = pd.read_sql("SELECT * FROM performance", conn)
    
    if df_p.empty:
        st.info("No data uploaded yet")
    else:
        df_p['date'] = pd.to_datetime(df_p['date'])
        
        # Summary statistics
        st.subheader("📊 Data Summary")
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
        
        # Upload history by date and channel
        st.subheader("Upload History")
        history = df_p.groupby(['date', 'channel']).agg({
            'campaign': 'count',
            'spend': 'sum',
            'sales': 'sum'
        }).reset_index()
        history.columns = ['Date', 'Channel', 'Records', 'Total Spend', 'Total Sales']
        history = history.sort_values('Date', ascending=False)
        
        st.dataframe(
            history.style.format({
                'Total Spend': '₹{:,.2f}',
                'Total Sales': '₹{:,.2f}'
            }),
            use_container_width=True,
            hide_index=True
        )

# --- 9. DASHBOARD ---
elif choice == "Dashboard":
    st.header("📊 Performance Dashboard")
    
    df_p = pd.read_sql("SELECT * FROM performance", conn)
    
    if df_p.empty: 
        st.info("📭 No data available. Please upload data using 'Upload Reports'.")
        st.stop()
    
    df_p['date'] = pd.to_datetime(df_p['date'])
    
    # Sidebar Filters
    st.sidebar.subheader("🎯 Filters")
    
    # Date range filter
    min_date = df_p['date'].min().date()
    max_date = df_p['date'].max().date()
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
        st.warning("No data matches your filters")
        st.stop()
    
    # Key Metrics
    t_spend, t_sales = f_df['spend'].sum(), f_df['sales'].sum()
    roas = t_sales / t_spend if t_spend > 0 else 0
    
    k1, k2, k3 = st.columns(3)
    k1.metric("Total Spend", f"₹{t_spend:,.0f}")
    k2.metric("Total Revenue", f"₹{t_sales:,.0f}")
    k3.metric("Overall ROAS", f"{roas:.2f}x")
    
    st.divider()
    
    # --- MULTI-CHANNEL TREND CHART ---
    st.subheader("📈 Efficiency Trend by Channel")
    
    # Aggregate data for charting
    ch_trend = f_df.groupby(['date', 'channel']).agg({'spend':'sum', 'sales':'sum'}).reset_index()
    ch_trend['ROAS'] = ch_trend['sales'] / ch_trend['spend']
    total_trend = f_df.groupby('date').agg({'spend':'sum', 'sales':'sum'}).reset_index()
    total_trend['ROAS'] = total_trend['sales'] / total_trend['spend']
    
    fig = go.Figure()
    
    # 1. Stacked Bars for Spend per Channel
    for channel in sorted(ch_trend['channel'].unique()):
        ch_data = ch_trend[ch_trend['channel'] == channel]
        fig.add_trace(go.Bar(
            x=ch_data['date'], 
            y=ch_data['spend'], 
            name=f"{channel} Spend"
        ))
    
    # 2. Individual Lines for ROAS per Channel
    for channel in sorted(ch_trend['channel'].unique()):
        ch_data = ch_trend[ch_trend['channel'] == channel]
        fig.add_trace(go.Scatter(
            x=ch_data['date'], 
            y=ch_data['ROAS'], 
            name=f"{channel} ROAS", 
            yaxis="y2", 
            mode='lines+markers'
        ))
    
    # 3. Total ROAS Line (Dashed)
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
    
    # Summary Tables
    c1, c2 = st.columns(2)
    with c1:
        st.write("**Performance by Channel**")
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
        st.write("**Performance by Product**")
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
    
    # Campaign Performance
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
    
    # --- DETAILED DATE-WISE DATA TABLE ---
    st.divider()
    st.subheader("📅 Detailed Date-wise Performance")
    
    # Prepare detailed table
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
    
    # Display with formatting
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
    
    # Download buttons
    col_d1, col_d2, col_d3 = st.columns(3)
    
    with col_d1:
        # Convert to CSV for download
        csv_data = detail_tab.to_csv(index=False)
        st.download_button(
            label="📥 Download as CSV",
            data=csv_data,
            file_name=f"marketing_performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col_d2:
        # Convert to Excel for download
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            detail_tab.to_excel(writer, index=False, sheet_name='Performance Data')
            
            # Add summary sheet
            summary_data = pd.DataFrame({
                'Metric': ['Total Spend', 'Total Revenue', 'Overall ROAS', 'Date Range', 'Total Records'],
                'Value': [
                    f"₹{t_spend:,.2f}",
                    f"₹{t_sales:,.2f}",
                    f"{roas:.2f}x",
                    f"{dr[0]} to {dr[1]}" if len(dr) == 2 else "All dates",
                    f"{len(detail_tab):,}"
                ]
            })
            summary_data.to_excel(writer, index=False, sheet_name='Summary')
        
        excel_data = excel_buffer.getvalue()
        st.download_button(
            label="📥 Download as Excel",
            data=excel_data,
            file_name=f"marketing_performance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlsheet",
            use_container_width=True
        )
    
    with col_d3:
        # Download aggregated summary
        summary_csv = pd.concat([
            channel_summary.reset_index().assign(Group='Channel'),
            product_summary.reset_index().assign(Group='Product')
        ])
        
        st.download_button(
            label="📥 Download Summary",
            data=summary_csv.to_csv(index=False),
            file_name=f"marketing_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# Footer
st.sidebar.divider()
st.sidebar.caption(f"👤 Logged in as: **{st.session_state.role}**")
if st.sidebar.button("🚪 Logout"):
    st.session_state.auth = False
    st.rerun()

# Database info
st.sidebar.divider()
st.sidebar.caption(f"💾 Database: `{st.session_state.db_path}`")
if os.path.exists(st.session_state.db_path):
    db_size = os.path.getsize(st.session_state.db_path) / 1024  # KB
    st.sidebar.caption(f"📊 Size: {db_size:.2f} KB")
    
    # Show record counts
    try:
        perf_count = c.execute("SELECT COUNT(*) FROM performance").fetchone()[0]
        st.sidebar.caption(f"📈 Records: {perf_count:,}")
    except:
        pass
