import streamlit as st
import pandas as pd
from datetime import datetime
from supabase import create_client

st.set_page_config(page_title="Database Diagnostics", page_icon="🔍", layout="wide")

st.title("🔍 Supabase Database Diagnostics")
st.caption("Debug tool to check data upload and retrieval")

# --- SUPABASE CONNECTION ---
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
    st.success("✅ Connected to Supabase")
except Exception as e:
    st.error(f"❌ Connection failed: {str(e)}")
    st.stop()

# --- DIAGNOSTIC SECTIONS ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Data Overview", "🔍 Date Query", "📝 Raw Data", "🧪 Test Query"])

# --- TAB 1: DATA OVERVIEW ---
with tab1:
    st.header("Database Overview")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Performance Table Stats")
        try:
            # Get all performance data
            response = supabase.table('performance').select('*').execute()
            df = pd.DataFrame(response.data)
            
            if not df.empty:
                st.metric("Total Records", f"{len(df):,}")
                
                # Show date range
                dates = pd.to_datetime(df['date'])
                st.metric("Earliest Date", dates.min().strftime('%Y-%m-%d'))
                st.metric("Latest Date", dates.max().strftime('%Y-%m-%d'))
                
                # Show unique counts
                st.metric("Unique Dates", df['date'].nunique())
                st.metric("Unique Channels", df['channel'].nunique())
                st.metric("Unique Products", df['product'].nunique())
                st.metric("Unique Campaigns", df['campaign'].nunique())
                
            else:
                st.warning("⚠️ Performance table is empty!")
                
        except Exception as e:
            st.error(f"Error reading performance table: {str(e)}")
    
    with col2:
        st.subheader("Master Data Stats")
        
        try:
            # Channels
            channels_resp = supabase.table('channels').select('*').execute()
            st.metric("Total Channels", len(channels_resp.data))
            
            # Products
            products_resp = supabase.table('products').select('*').execute()
            st.metric("Total Products", len(products_resp.data))
            
            # Mappings
            mappings_resp = supabase.table('mappings').select('*').execute()
            st.metric("Total Mappings", len(mappings_resp.data))
            
        except Exception as e:
            st.error(f"Error reading master data: {str(e)}")
    
    # Show date distribution
    if not df.empty:
        st.divider()
        st.subheader("📅 Data by Date")
        
        date_summary = df.groupby('date').agg({
            'id': 'count',
            'spend': 'sum',
            'sales': 'sum'
        }).reset_index()
        date_summary.columns = ['Date', 'Records', 'Total Spend', 'Total Sales']
        date_summary = date_summary.sort_values('Date', ascending=False)
        
        st.dataframe(
            date_summary.style.format({
                'Total Spend': '₹{:,.2f}',
                'Total Sales': '₹{:,.2f}'
            }),
            use_container_width=True
        )
        
        # Check for March 28 and 29
        st.divider()
        st.subheader("🎯 Checking for March 28 & 29, 2026")
        
        march_28 = df[df['date'] == '2026-03-28']
        march_29 = df[df['date'] == '2026-03-29']
        
        col1, col2 = st.columns(2)
        with col1:
            if not march_28.empty:
                st.success(f"✅ March 28: Found {len(march_28)} records")
                st.dataframe(march_28[['channel', 'campaign', 'product', 'spend', 'sales']])
            else:
                st.error("❌ March 28: No records found")
        
        with col2:
            if not march_29.empty:
                st.success(f"✅ March 29: Found {len(march_29)} records")
                st.dataframe(march_29[['channel', 'campaign', 'product', 'spend', 'sales']])
            else:
                st.error("❌ March 29: No records found")

# --- TAB 2: DATE QUERY ---
with tab2:
    st.header("🔍 Search by Date")
    
    search_date = st.date_input("Select Date to Search", value=datetime(2026, 3, 28).date())
    
    if st.button("🔎 Search", type="primary"):
        search_str = search_date.strftime('%Y-%m-%d')
        
        try:
            # Query specific date
            response = supabase.table('performance').select('*').eq('date', search_str).execute()
            
            if response.data:
                st.success(f"✅ Found {len(response.data)} records for {search_str}")
                
                df_result = pd.DataFrame(response.data)
                
                # Show summary
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Spend", f"₹{df_result['spend'].sum():,.2f}")
                with col2:
                    st.metric("Total Sales", f"₹{df_result['sales'].sum():,.2f}")
                with col3:
                    roas = df_result['sales'].sum() / df_result['spend'].sum() if df_result['spend'].sum() > 0 else 0
                    st.metric("ROAS", f"{roas:.2f}x")
                
                # Show detailed data
                st.subheader("Detailed Records")
                st.dataframe(
                    df_result[['date', 'channel', 'campaign', 'product', 'spend', 'sales']].style.format({
                        'spend': '₹{:,.2f}',
                        'sales': '₹{:,.2f}'
                    }),
                    use_container_width=True
                )
                
            else:
                st.error(f"❌ No records found for {search_str}")
                
                # Try alternative date formats
                st.info("🔄 Trying alternative date formats...")
                
                # Try with different separators
                alt_formats = [
                    search_date.strftime('%Y/%m/%d'),
                    search_date.strftime('%d-%m-%Y'),
                    search_date.strftime('%d/%m/%Y'),
                    search_date.strftime('%m-%d-%Y'),
                    search_date.strftime('%Y%m%d')
                ]
                
                found = False
                for alt_format in alt_formats:
                    response = supabase.table('performance').select('*').eq('date', alt_format).execute()
                    if response.data:
                        st.success(f"✅ Found data with format: {alt_format}")
                        st.dataframe(pd.DataFrame(response.data))
                        found = True
                        break
                
                if not found:
                    st.warning("⚠️ No data found in any date format. The data may not have been uploaded.")
                
        except Exception as e:
            st.error(f"Error querying database: {str(e)}")

# --- TAB 3: RAW DATA ---
with tab3:
    st.header("📝 Raw Database Contents")
    
    if st.button("📥 Load All Data", type="primary"):
        try:
            # Get all data with ordering
            response = supabase.table('performance').select('*').order('date', desc=True).execute()
            
            if response.data:
                df_all = pd.DataFrame(response.data)
                
                st.success(f"✅ Loaded {len(df_all)} records")
                
                # Show raw data
                st.dataframe(df_all, use_container_width=True, height=600)
                
                # Download option
                csv = df_all.to_csv(index=False)
                st.download_button(
                    label="📥 Download Full Dataset",
                    data=csv,
                    file_name=f"supabase_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv"
                )
                
            else:
                st.warning("⚠️ No data in performance table")
                
        except Exception as e:
            st.error(f"Error loading data: {str(e)}")

# --- TAB 4: TEST QUERY ---
with tab4:
    st.header("🧪 Test Custom Query")
    
    st.info("Test different query patterns to debug data retrieval")
    
    # Test 1: Get all dates
    if st.button("1️⃣ Get All Unique Dates"):
        try:
            response = supabase.table('performance').select('date').execute()
            if response.data:
                dates = sorted(list(set([item['date'] for item in response.data])))
                st.success(f"Found {len(dates)} unique dates")
                st.write(dates)
            else:
                st.warning("No dates found")
        except Exception as e:
            st.error(f"Error: {str(e)}")
    
    # Test 2: Get March 2026 data
    if st.button("2️⃣ Get All March 2026 Data"):
        try:
            response = supabase.table('performance').select('*').execute()
            if response.data:
                df = pd.DataFrame(response.data)
                # Filter for March 2026
                march_data = df[df['date'].str.startswith('2026-03')]
                
                if not march_data.empty:
                    st.success(f"Found {len(march_data)} records for March 2026")
                    
                    # Show date breakdown
                    date_counts = march_data['date'].value_counts().sort_index()
                    st.write("Records per date:")
                    st.dataframe(date_counts)
                    
                    st.divider()
                    st.write("Full March 2026 data:")
                    st.dataframe(march_data)
                else:
                    st.warning("No March 2026 data found")
            else:
                st.warning("No data found")
        except Exception as e:
            st.error(f"Error: {str(e)}")
    
    # Test 3: Check date format consistency
    if st.button("3️⃣ Check Date Format Consistency"):
        try:
            response = supabase.table('performance').select('date').execute()
            if response.data:
                dates = [item['date'] for item in response.data]
                
                # Check formats
                formats = {}
                for date in dates:
                    if '-' in date and date.count('-') == 2:
                        parts = date.split('-')
                        if len(parts[0]) == 4:
                            formats['YYYY-MM-DD'] = formats.get('YYYY-MM-DD', 0) + 1
                        else:
                            formats['DD-MM-YYYY'] = formats.get('DD-MM-YYYY', 0) + 1
                    elif '/' in date:
                        formats['Uses /'] = formats.get('Uses /', 0) + 1
                    else:
                        formats['Other'] = formats.get('Other', 0) + 1
                
                st.success("Date format analysis:")
                st.json(formats)
                
                # Show sample dates
                st.write("Sample dates:")
                st.write(dates[:20])
            else:
                st.warning("No dates found")
        except Exception as e:
            st.error(f"Error: {str(e)}")
    
    # Test 4: Query with LIKE pattern
    st.divider()
    st.subheader("Custom Pattern Search")
    
    pattern = st.text_input("Enter date pattern (e.g., '2026-03%' for March 2026)", "2026-03%")
    
    if st.button("4️⃣ Search with Pattern"):
        try:
            # Note: Supabase uses PostgREST which supports pattern matching
            response = supabase.table('performance').select('*').like('date', pattern).execute()
            
            if response.data:
                st.success(f"Found {len(response.data)} records")
                st.dataframe(pd.DataFrame(response.data))
            else:
                st.warning("No records found with this pattern")
                
        except Exception as e:
            st.error(f"Error: {str(e)}")
            st.info("Pattern matching might not be supported. Try using the raw data view instead.")

# --- FOOTER ---
st.divider()
st.caption(f"Diagnostic Tool | Connected to Supabase | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
