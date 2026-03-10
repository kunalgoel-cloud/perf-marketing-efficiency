import streamlit as st
import pandas as pd
import sqlite3
import io
import plotly.graph_objects as go

# --- DATABASE SETUP ---
conn = sqlite3.connect('marketing_v8.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS products (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS channels (name TEXT UNIQUE)')
c.execute('CREATE TABLE IF NOT EXISTS mappings (campaign TEXT, product_name TEXT, UNIQUE(campaign, product_name))')
c.execute('CREATE TABLE IF NOT EXISTS performance (date TEXT, channel TEXT, campaign TEXT, product TEXT, spend REAL, sales REAL, clicks REAL, orders REAL)')
conn.commit()

# --- STANDARDIZATION LOGIC ---
def standardize_data(df, manual_date=None):
    mapping = {
        'METRICS_DATE': 'date', 'CAMPAIGN_NAME': 'campaign', 
        'TOTAL_BUDGET_BURNT': 'spend', 'TOTAL_SPEND': 'spend',
        'TOTAL_GMV': 'sales', 'Campaign name': 'campaign', 
        'Total cost': 'spend', 'Sales': 'sales', 
        'Campaign start date': 'date', 'Date': 'date', 
        'Ad Spend': 'spend', 'Ad Revenue': 'sales'
    }
    df = df.rename(columns=mapping)
    
    # 1. Date Handling
    if manual_date:
        df['date'] = manual_date.strftime('%Y-%m-%d')
    else:
        # Robust parsing for mixed formats (Swiggy vs Amazon)
        df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
        df = df.dropna(subset=['date'])
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

    # 2. Cleanup Numeric & Zero Spend
    for col in ['spend', 'sales']:
        if col not in df.columns: df[col] = 0.0
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[₹,]', '', regex=True), errors='coerce').fillna(0)
    
    df = df[df['spend'] > 0].copy()
    if 'campaign' not in df.columns: df['campaign'] = "CHANNEL_TOTAL"
    
    return df

# --- UI LOGIC ---
if 'auth' not in st.session_state: st.session_state.auth = False

# (Authentication block same as before...)

choice = st.sidebar.selectbox("Navigation", ["Dashboard", "Upload", "Settings"])

if choice == "Upload":
    st.header("Upload Marketing Data")
    
    col_a, col_b = st.columns(2)
    with col_a:
        chs = [r[0] for r in c.execute("SELECT name FROM channels").fetchall()]
        sel_ch = st.selectbox("Select Channel", chs)
    with col_b:
        # NEW: Manual Date Option
        upload_date = st.date_input("Assign Date to this Upload (Optional)", value=None, help="If left blank, the system will use dates found inside the file.")

    file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])

    if file:
        raw_df = robust_read_file(file) # Uses the robust reader from previous steps
        if raw_df is not None:
            df = standardize_data(raw_df, manual_date=upload_date)
            st.write(f"Preview (Date assigned: {upload_date if upload_date else 'From File'}):")
            st.dataframe(df.head(), hide_index=True)

            # Mapping & Multi-Product Split Logic
            mapping_db = {}
            for row in c.execute("SELECT campaign, product_name FROM mappings").fetchall():
                mapping_db.setdefault(row[0], []).append(row[1])
            
            unique_camps = df['campaign'].unique()
            unmapped = [cp for cp in unique_camps if cp not in mapping_db]
            
            if unmapped:
                st.warning(f"Map {len(unmapped)} New Campaigns")
                prods = [r[0] for r in c.execute("SELECT name FROM products").fetchall()] + ["Brand/Global"]
                
                for cp in unmapped:
                    selected = st.multiselect(f"Assign product(s) for: {cp}", prods, key=cp)
                    if selected:
                        for p_name in selected:
                            c.execute("INSERT OR IGNORE INTO mappings VALUES (?,?)", (cp, p_name))
                
                if st.button("Confirm Mappings"):
                    conn.commit()
                    st.rerun()
            else:
                if st.button("Finalize & Save Data"):
                    for _, row in df.iterrows():
                        target_prods = mapping_db.get(row['campaign'], ["Unmapped"])
                        n = len(target_prods)
                        for p_name in target_prods:
                            c.execute("INSERT INTO performance VALUES (?,?,?,?,?,?,?,?)", 
                                      (row['date'], sel_ch, row['campaign'], p_name, row['spend']/n, row['sales']/n, 0, 0))
                    conn.commit()
                    st.success("Successfully saved to dashboard!")
