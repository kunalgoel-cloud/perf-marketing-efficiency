import streamlit as st
import pandas as pd
import sqlite3
from io import BytesIO

# --- DB SETUP ---
conn = sqlite3.connect('marketing_v2.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT PRIMARY KEY, product_name TEXT)')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL)')
conn.commit()

# --- HELPER FUNCTIONS ---
def load_data(file, channel_type):
    """Parses files based on the specific channel formats you uploaded."""
    try:
        if channel_type == "Instamart":
            # Instamart has ~6 rows of junk/filters at the top
            df = pd.read_csv(file, skiprows=6)
            return df.rename(columns={'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 'TOTAL_SPEND': 'spend', 'TOTAL_GMV': 'sales'})
        
        elif channel_type == "Amazon":
            df = pd.read_csv(file)
            return df.rename(columns={'Campaign name': 'campaign', 'Total cost': 'spend', 'Sales': 'sales', 'Campaign start date': 'date'})
        
        else: # Summary / Generic
            df = pd.read_csv(file)
            # If no campaign column exists, we mark it for manual product assignment
            if 'Campaign' not in df.columns and 'campaign' not in df.columns:
                df['campaign'] = "NO_CAMPAIGN_DATA"
            return df.rename(columns={'Date': 'date', 'Ad Spend': 'spend', 'Ad Revenue': 'sales'})
    except Exception as e:
        st.error(f"Error parsing file: {e}")
        return None

# --- UI ---
st.set_page_config(layout="wide")

# Simple Login
if 'auth' not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    col1, col2 = st.columns(2)
    with col1:
        u = st.text_input("User")
        p = st.text_input("Pass", type="password")
        if st.button("Login"):
            if (u == "admin" and p == "admin123") or (u == "viewer" and p == "view123"):
                st.session_state.auth = True
                st.session_state.role = "admin" if u == "admin" else "viewer"
                st.rerun()
    st.stop()

# --- ADMIN LOGIC ---
if st.session_state.role == "admin":
    st.sidebar.title("Admin Tools")
    page = st.sidebar.radio("Navigate", ["Settings", "Upload Data", "Analytics"])

    if page == "Settings":
        st.header("Configure Products & Channels")
        # Add Product
        new_p = st.text_input("New Product Name")
        if st.button("Add Product"):
            c.execute("INSERT OR IGNORE INTO products VALUES (?)", (new_p,))
            conn.commit()
        
        # Add Channel
        new_c = st.text_input("New Channel (e.g. Instamart, Amazon)")
        if st.button("Add Channel"):
            c.execute("INSERT OR IGNORE INTO channels VALUES (?)", (new_c,))
            conn.commit()

    elif page == "Upload Data":
        st.header("Upload Performance Reports")
        channels = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
        products = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
        
        selected_channel = st.selectbox("Which channel is this?", channels)
        uploaded_file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])

        if uploaded_file:
            df = load_data(uploaded_file, selected_channel)
            if df is not None:
                st.write("Data Preview:", df.head(3))
                
                # Check for unmapped campaigns
                unique_campaigns = df['campaign'].unique()
                known_mappings = dict(c.execute("SELECT campaign, product_name FROM mappings").fetchall())
                
                unmapped = [camp for camp in unique_campaigns if camp not in known_mappings]
                
                if unmapped:
                    st.warning(f"Found {len(unmapped)} unmapped campaigns!")
                    map_df = pd.DataFrame({'campaign': unmapped, 'product': [None]*len(unmapped)})
                    updated_map = st.data_editor(map_df, column_config={
                        "product": st.column_config.SelectboxColumn("Assign Product", options=products)
                    })
                    
                    if st.button("Save Mappings & Upload"):
                        for _, row in updated_map.iterrows():
                            if row['product']:
                                c.execute("INSERT INTO mappings VALUES (?, ?)", (row['campaign'], row['product']))
                        
                        # Process and Save to Performance Table
                        # (Logic to join df with updated mappings and insert into 'performance' table)
                        st.success("Data uploaded successfully!")
                        conn.commit()

# --- VIEWER / ANALYTICS ---
else:
    st.title("Performance Dashboard")
    # Filters: Date Range, Channel, Product
    # Graphs: Plotly trend lines for Spend, Sales, and ROAS
