import streamlit as st
import pandas as pd
import sqlite3
import io

# --- DB SETUP ---
conn = sqlite3.connect('marketing_v4.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT PRIMARY KEY, product_name TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL)')
conn.commit()

def robust_read_file(file):
    """Handles Excel and CSV with multiple encoding fallbacks."""
    file_name = file.name.lower()
    
    # Handle Excel
    if file_name.endswith('.xlsx') or file_name.endswith('.xls'):
        try:
            return pd.read_excel(file)
        except Exception as e:
            st.error(f"Excel Error: {e}")
            return None

    # Handle CSV with Encoding Fallbacks
    bytes_data = file.read()
    for encoding in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            # First try standard read
            df = pd.read_csv(io.BytesIO(bytes_data), encoding=encoding)
            # If it's Instamart (METRICS_DATE is in row 6), re-read skipping rows
            if 'METRICS_DATE' not in df.columns and 'Selected Filters' in str(df.columns):
                 df = pd.read_csv(io.BytesIO(bytes_data), encoding=encoding, skiprows=6)
            return df
        except Exception:
            continue
    return None

def standardize_data(df):
    """Renames headers from your specific files to common keys."""
    cols = df.columns.tolist()
    
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 'TOTAL_SPEND': 'spend', 'TOTAL_GMV': 'sales', # Instamart
        'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 'Campaign start date': 'date', # Amazon
        'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales' # Blinkit/Summary
    }
    
    df = df.rename(columns=mapping)
    
    # Ensure mandatory columns exist
    if 'campaign' not in df.columns:
        df['campaign'] = "CHANNEL_TOTAL_UNSPECIFIED"
    
    # Clean numeric data
    for col in ['spend', 'sales']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    return df

# --- AUTH ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("Login")
    u, p = st.text_input("User"), st.text_input("Pass", type="password")
    if st.button("Login"):
        if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
            st.session_state.authenticated, st.session_state.role = True, u
            st.rerun()
    st.stop()

# --- MAIN APP ---
if st.session_state.role == "admin":
    menu = ["Analytics", "Data Upload", "Configuration"]
else:
    menu = ["Analytics"]

choice = st.sidebar.selectbox("Navigation", menu)

if choice == "Configuration":
    st.header("System Settings")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Channels")
        new_ch = st.text_input("Add Channel (e.g., Blinkit)")
        if st.button("Add"):
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_ch,))
            conn.commit()
        
        # SHOW CURRENT CHANNELS
        channels_df = pd.read_sql("SELECT name FROM channels", conn)
        st.dataframe(channels_df, use_container_width=True, hide_index=True)

    with col2:
        st.subheader("Products")
        new_pr = st.text_input("Add Product (e.g., Farali Mixture)")
        if st.button("Add "):
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_pr,))
            conn.commit()
            
        # SHOW CURRENT PRODUCTS
        products_df = pd.read_sql("SELECT name FROM products", conn)
        st.dataframe(products_df, use_container_width=True, hide_index=True)

elif choice == "Data Upload":
    st.header("Upload Marketing Reports")
    
    channels = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
    if not channels:
        st.warning("Please add a channel in 'Configuration' first.")
    else:
        selected_ch = st.selectbox("Select Target Channel", channels)
        file = st.file_uploader("Upload CSV or Excel", type=['csv', 'xlsx', 'xls'])

        if file:
            raw_df = robust_read_file(file)
            if raw_df is not None:
                df = standardize_data(raw_df)
                st.write("Preview of Cleaned Data:", df.head(3))
                
                # Campaign Memory Management
                mapping_db = dict(c.execute("SELECT campaign, product_name FROM mappings").fetchall())
                unique_camps = df['campaign'].unique()
                unmapped = [cp for cp in unique_camps if cp not in mapping_db]
                
                if unmapped:
                    st.warning(f"Map {len(unmapped)} new campaigns to products:")
                    prod_list = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                    
                    # Mapping Editor
                    map_df = pd.DataFrame({'campaign': unmapped, 'product_name': [None]*len(unmapped)})
                    res = st.data_editor(map_df, column_config={
                        "product_name": st.column_config.SelectboxColumn("Assign Product", options=prod_list, required=True)
                    }, hide_index=True)
                    
                    if st.button("Save & Process"):
                        for _, row in res.iterrows():
                            if row['product_name']:
                                c.execute("INSERT OR REPLACE INTO mappings VALUES (?,?)", (row['campaign'], row['product_name']))
                        conn.commit()
                        st.success("Mappings saved! Next time this file is uploaded, it will auto-process.")

elif choice == "Analytics":
    st.title("Performance Analytics Dashboard")
    st.info("Charts will display here based on stored 'performance' table data.")
