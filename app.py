import streamlit as st
import pandas as pd

# --- MOCK DATABASE (In a real app, use SQLite or PostgreSQL) ---
if 'mapping_db' not in st.session_state:
    # Campaign Name -> Product Name
    st.session_state.mapping_db = pd.DataFrame(columns=['Campaign', 'Product'])

if 'products' not in st.session_state:
    st.session_state.products = ['Product A', 'Product B', 'Brand/Global']

def save_mapping(new_mappings):
    st.session_state.mapping_db = pd.concat([st.session_state.mapping_db, new_mappings]).drop_duplicates('Campaign')

# --- ADMIN PAGE UI ---
st.title("Admin: Ad Report Upload")

uploaded_file = st.file_uploader("Upload Channel Report (CSV)", type="csv")

if uploaded_file:
    # 1. Load the raw data
    raw_df = pd.read_csv(uploaded_file)
    st.write("### Raw Data Preview", raw_df.head())
    
    # 2. Identify Campaigns not in our "Memory"
    existing_campaigns = st.session_state.mapping_db['Campaign'].tolist()
    uploaded_campaigns = raw_df['Campaign Name'].unique()
    
    new_campaigns = [c for c in uploaded_campaigns if c not in existing_campaigns]
    
    if new_campaigns:
        st.warning(f"Found {len(new_campaigns)} new campaigns. Please map them to products.")
        
        # Create a temporary dataframe for the Admin to fill out
        to_map_df = pd.DataFrame({'Campaign': new_campaigns, 'Product': None})
        
        # 3. The "Memory" Editor
        # This allows the admin to select the product from a dropdown
        updated_mapping = st.data_editor(
            to_map_df,
            column_config={
                "Product": st.column_config.SelectboxColumn(
                    "Assign Product",
                    options=st.session_state.products,
                    required=True,
                )
            },
            hide_index=True,
        )
        
        if st.button("Save Mappings & Process Report"):
            save_mapping(updated_mapping)
            st.success("Mappings updated! System will now remember these for next time.")
            # Proceed to calculate product-level spend...
    else:
        st.info("All campaigns recognized. Processing data...")
