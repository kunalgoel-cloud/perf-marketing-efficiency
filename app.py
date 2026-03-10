import streamlit as st
import pandas as pd
import sqlite3

# --- DATABASE SETUP ---
conn = sqlite3.connect('marketing_db.db', check_same_thread=False)
c = conn.cursor()

# Create tables if they don't exist
c.execute('CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (id INTEGER PRIMARY KEY, name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT PRIMARY KEY, product_id INTEGER)')
c.execute('CREATE TABLE IF NOT EXISTS raw_spend (date TEXT, channel TEXT, campaign TEXT, spend REAL, sales REAL, cpc REAL, cac REAL)')
conn.commit()

# --- LOGIN LOGIC (Simplified for Demo) ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    with st.form("Login"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            if user == "admin" and pw == "admin123": # Replace with secure logic
                st.session_state.role = "admin"
                st.session_state.logged_in = True
                st.rerun()
            elif user == "viewer" and pw == "view123":
                st.session_state.role = "viewer"
                st.session_state.logged_in = True
                st.rerun()
    st.stop()

# --- ADMIN DASHBOARD ---
if st.session_state.role == "admin":
    st.title("Admin Control Panel")
    
    tab1, tab2, tab3 = st.tabs(["Settings (Products/Channels)", "Data Upload", "Manage Data"])

    # TAB 1: Configuration
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            new_prod = st.text_input("Add New Product")
            if st.button("Save Product"):
                c.execute('INSERT OR IGNORE INTO products (name) VALUES (?)', (new_prod,))
                conn.commit()
            st.write("Current Products:", pd.read_sql("SELECT name FROM products", conn))

        with col2:
            new_chan = st.text_input("Add New Channel")
            if st.button("Save Channel"):
                c.execute('INSERT OR IGNORE INTO channels (name) VALUES (?)', (new_chan,))
                conn.commit()
            st.write("Current Channels:", pd.read_sql("SELECT name FROM channels", conn))

    # TAB 2: Upload (CSV or Excel)
    with tab2:
        channel_list = pd.read_sql("SELECT name FROM channels", conn)['name'].tolist()
        selected_channel = st.selectbox("Select Channel for this Upload", channel_list)
        
        uploaded_file = st.file_uploader("Upload Ad Report", type=['csv', 'xlsx'])
        
        if uploaded_file:
            # Handle CSV or Excel
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            st.write("Preview:", df.head())
            
            # --- Campaign Memory Logic ---
            # (Identify campaigns in df not in 'mappings' table and use st.data_editor to map them)
            st.info("System will now check for unlinked campaigns...")

    # TAB 3: Data Deletion
    with tab3:
        st.subheader("Delete Data by Context")
        del_date = st.date_input("Select Date")
        del_chan = st.selectbox("Select Channel to Clear", channel_list)
        if st.button("Delete Records"):
            c.execute('DELETE FROM raw_spend WHERE date = ? AND channel = ?', (str(del_date), del_chan))
            conn.commit()
            st.warning(f"Deleted records for {del_chan} on {del_date}")

# --- VIEWER DASHBOARD ---
else:
    st.title("Marketing Performance Analytics")
    # Insert Graphing/Filtering Logic here...
