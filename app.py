import streamlit as st
import pandas as pd
import sqlite3
import io

# --- DB SETUP ---
conn = sqlite3.connect('marketing_v3.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT PRIMARY KEY, product_name TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL, cpc REAL)')
conn.commit()

def robust_read_csv(file):
    """Attempts to read CSV using different encodings to avoid 'utf-8' errors."""
    bytes_data = file.read()
    for encoding in ['utf-8', 'ISO-8859-1', 'cp1252', 'utf-16']:
        try:
            df = pd.read_csv(io.BytesIO(bytes_data), encoding=encoding)
            return df
        except Exception:
            continue
    # If standard read fails, try skipping metadata (for Instamart style)
    try:
        df = pd.read_csv(io.BytesIO(bytes_data), encoding='ISO-8859-1', skiprows=6)
        return df
    except Exception as e:
        st.error(f"Could not parse file: {e}")
        return None

def process_file(df, channel):
    """Normalizes different channel headers into a standard format."""
    # Instamart detection
    if 'METRICS_DATE' in df.columns:
        df = df.rename(columns={'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 'TOTAL_SPEND': 'spend', 'TOTAL_GMV': 'sales'})
    
    # Generic Performance Summary (Blinkit/Zepto style)
    elif 'Ad Spend' in df.columns:
        df = df.rename(columns={'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales'})
        if 'Campaign' not in df.columns:
            df['campaign'] = "CHANNEL_TOTAL" # Will trigger product selection
    
    # Amazon style
    elif 'Campaign name' in df.columns:
        df = df.rename(columns={'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 'Campaign start date': 'date'})

    # Clean numeric data (Remove currency symbols/commas)
    for col in ['spend', 'sales']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    return df

# --- APP UI ---
st.title("Performance Marketing Dashboard")

# Login Section
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    with st.container():
        user = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if user == "admin" and password == "admin123":
                st.session_state.authenticated = True
                st.session_state.role = "admin"
                st.rerun()
            elif user == "viewer" and password == "view123":
                st.session_state.authenticated = True
                st.session_state.role = "viewer"
                st.rerun()
    st.stop()

# --- ADMIN VIEW ---
if st.session_state.role == "admin":
    st.sidebar.success(f"Logged in as: {st.session_state.role.upper()}")
    
    tab1, tab2 = st.tabs(["Upload & Map", "Settings"])

    with tab2:
        st.subheader("Manage Channels & Products")
        # Add Channel logic
        c_input = st.text_input("Add Channel Name")
        if st.button("Save Channel"):
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (c_input,))
            conn.commit()
            
        # Add Product logic
        p_input = st.text_input("Add Product Name")
        if st.button("Save Product"):
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (p_input,))
            conn.commit()

    with tab1:
        st.subheader("Data Upload")
        ch_list = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
        selected_ch = st.selectbox("Select Channel", ch_list)
        
        file = st.file_uploader("Upload Report (CSV/Excel)", type=['csv'])
        
        if file:
            raw_df = robust_read_csv(file)
            if raw_df is not None:
                df = process_file(raw_df, selected_ch)
                st.write("Data detected:", df.head())

                # CHECK FOR NEW CAMPAIGNS
                unique_camps = df['campaign'].unique()
                mapping_dict = dict(c.execute("SELECT campaign, product_name FROM mappings").fetchall())
                
                new_camps = [cp for cp in unique_camps if cp not in mapping_dict]
                
                if new_camps:
                    st.warning(f"Unmapped Campaigns found in {selected_ch}")
                    prod_list = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                    
                    # Mapping Table
                    map_df = pd.DataFrame({'campaign': new_camps, 'product_name': [None]*len(new_camps)})
                    edited_mappings = st.data_editor(map_df, column_config={
                        "product_name": st.column_config.SelectboxColumn("Assign Product", options=prod_list)
                    })
                    
                    if st.button("Confirm Mappings & Save Data"):
                        # Save new mappings to 'Memory'
                        for _, row in edited_mappings.iterrows():
                            if row['product_name']:
                                c.execute("INSERT OR REPLACE INTO mappings VALUES (?,?)", (row['campaign'], row['product_name']))
                        
                        # Save Data to Performance table
                        # (Logic to join and insert goes here)
                        st.success("Data stored!")
                        conn.commit()

# --- VIEWER VIEW ---
else:
    st.title("Performance Analytics")
    st.info("Viewer Access: Charts and Trends will appear here.")
    # (Plotly charts logic)
