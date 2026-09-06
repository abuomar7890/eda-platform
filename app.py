import streamlit as st
from supabase import create_client, Client
import socket
import uuid
import pandas as pd
import io
import plotly.express as px  # مكتبة الرسم البياني

st.set_page_config(page_title="EDA Platform", page_icon="📊", layout="wide")

# --- تهيئة الاتصال بـ Supabase ---
@st.cache_resource
def init_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

try:
    supabase: Client = init_supabase()
except Exception:
    st.error("تعذر الاتصال بـ Supabase. تحقق من رابط المشروع ومفتاح API في secrets.toml.")
    st.stop()

# --- إدارة حالة الجلسة ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_email' not in st.session_state:
    st.session_state.user_email = None
if 'user_id' not in st.session_state:
    st.session_state.user_id = None

# --- دوال المصادقة ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.logged_in = True
        st.session_state.user_email = email
        user_data = supabase.auth.get_user()
        if user_data.user:
            st.session_state.user_id = user_data.user.id
        st.success("تم تسجيل الدخول بنجاح!")
        st.rerun()
    except socket.gaierror:
        st.error("تعذر الوصول إلى خادم Supabase.")
    except Exception as e:
        st.error(f"خطأ في تسجيل الدخول: {e}")

def signup(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        st.success("تم إنشاء الحساب بنجاح!")
    except socket.gaierror:
        st.error("تعذر الوصول إلى خادم Supabase.")
    except Exception as e:
        st.error(f"خطأ: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.logged_in = False
    st.session_state.user_email = None
    st.session_state.user_id = None
    st.rerun()

# --- دوال مساعدة ---
def get_correct_mime_type(file_name):
    extension = file_name.split('.')[-1].lower()
    mime_types = {
        'csv': 'text/csv',
        'xls': 'application/vnd.ms-excel',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'json': 'application/json',
        'tsv': 'text/tab-separated-values',
        'parquet': 'application/octet-stream'
    }
    return mime_types.get(extension, 'application/octet-stream')

def validate_file(uploaded_file):
    MAX_SIZE_MB = 10
    file_size_mb = uploaded_file.size / (1024 * 1024)
    if file_size_mb > MAX_SIZE_MB:
        return False, f"حجم الملف كبير جداً ({file_size_mb:.2f} ميجابايت)."
    allowed_extensions = ['csv', 'xls', 'xlsx', 'json', 'tsv', 'parquet']
    file_extension = uploaded_file.name.split('.')[-1].lower()
    if file_extension not in allowed_extensions:
        return False, f"امتداد الملف غير مدعوم ({file_extension})."
    return True, None

# --- دوال Storage ---
def upload_file_to_storage(uploaded_file, file_path):
    try:
        file_bytes = uploaded_file.read()
        correct_mime_type = get_correct_mime_type(uploaded_file.name)
        response = supabase.storage.from_('eda-uploads').upload(
            file_path, file_bytes, file_options={"content_type": correct_mime_type}
        )
        return True, response
    except Exception as e:
        return False, str(e)

def save_file_metadata(user_id, email, file_name, file_size, file_type, file_path):
    try:
        data = {
            "user_id": user_id, "email": email, "file_name": file_name,
            "file_size": file_size, "file_type": file_type, "file_path": file_path
        }
        result = supabase.table("files").insert(data).execute()
        return True, result
    except Exception as e:
        return False, str(e)

def get_user_files(user_id):
    try:
        result = supabase.table("files").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return result.data
    except Exception as e:
        st.error(f"خطأ في جلب الملفات: {e}")
        return []

def delete_file(file_id, file_path):
    errors = []
    try:
        supabase.storage.from_('eda-uploads').remove([file_path])
    except Exception as e:
        errors.append(f"Storage: {str(e)}")
    try:
        result = supabase.table("files").delete().eq("id", file_id).execute()
        if hasattr(result, 'error') and result.error:
            errors.append(f"Database: {result.error.message}")
    except Exception as e:
        errors.append(f"Database: {str(e)}")
    return len(errors) == 0, errors

def download_file(file_path):
    try:
        return supabase.storage.from_('eda-uploads').download(file_path)
    except Exception:
        return None

# ==========================================
# دالة قراءة البيانات للتحليل
# ==========================================
def load_data_for_eda(file_bytes, file_name):
    try:
        extension = file_name.split('.')[-1].lower()
        if extension == 'csv':
            df = pd.read_csv(io.BytesIO(file_bytes))
        elif extension in ['xls', 'xlsx']:
            df = pd.read_excel(io.BytesIO(file_bytes))
        elif extension == 'json':
            df = pd.read_json(io.BytesIO(file_bytes))
        elif extension == 'parquet':
            df = pd.read_parquet(io.BytesIO(file_bytes))
        else:
            return None, "امتداد الملف غير مدعوم للقراءة المباشرة في هذه المرحلة."
        return df, None
    except Exception as e:
        return None, f"فشل قراءة الملف: {str(e)}"

# --- واجهة المستخدم ---
def main():
    if st.session_state.logged_in:
        st.title(f"مرحباً بك، {st.session_state.user_email} 👋")
        
        tab_home, tab_upload, tab_files, tab_eda = st.tabs([
            "🏠 الرئيسية", "📤 رفع الملفات", "📁 ملفاتي", "🔍 فهم البيانات"
        ])
        
        with tab_home:
            st.write("أنت الآن في الصفحة الرئيسية لمنصة التحليل الاستكشافي.")
            st.write("⚠️ المشروع قيد التطوير، سيتم إضافة صفحات التحليل قريباً!")
            if st.button("تسجيل الخروج"):
                logout()
        
        with tab_upload:
            st.subheader("📤 رفع ملف بيانات جديد")
            st.info("**الأنواع المسموحة:** CSV, Excel, JSON, TSV, Parquet | **الحد الأقصى:** 10 ميجابايت")
            uploaded_file = st.file_uploader("اختر ملفاً للرفع", type=['csv', 'xls', 'xlsx', 'json', 'tsv', 'parquet'])
            
            if uploaded_file is not None:
                if st.button("🚀 رفع الملف", type="primary"):
                    with st.spinner("جاري رفع الملف..."):
                        is_valid, error_msg = validate_file(uploaded_file)
                        if not is_valid:
                            st.error(f"❌ {error_msg}")
                        else:
                            file_extension = uploaded_file.name.split('.')[-1].lower()
                            unique_filename = f"{st.session_state.user_id}/{uuid.uuid4()}.{file_extension}"
                            success, result = upload_file_to_storage(uploaded_file, unique_filename)
                            
                            if success:
                                meta_success, meta_result = save_file_metadata(
                                    st.session_state.user_id, st.session_state.user_email,
                                    uploaded_file.name, uploaded_file.size,
                                    get_correct_mime_type(uploaded_file.name), unique_filename
                                )
                                if meta_success:
                                    st.success("✅ تم رفع الملف بنجاح!")
                                    st.balloons()
                                else:
                                    st.warning(f"⚠️ فشل حفظ البيانات: {meta_result}")
                            else:
                                st.error(f"❌ فشل الرفع: {result}")
        
        with tab_files:
            st.subheader("📁 ملفاتي المرفوعة")
            if st.button("🔄 تحديث القائمة"):
                st.rerun()
            
            user_files = get_user_files(st.session_state.user_id)
            if len(user_files) == 0:
                st.info("📭 لا توجد ملفات مرفوعة.")
            else:
                st.success(f"✅ لديك {len(user_files)} ملف(ات)")
                st.markdown("---")
                for file in user_files:
                    with st.container():
                        col_name, col_size, col_date, col_actions = st.columns([3, 1, 1, 2])
                        with col_name:
                            st.write(f"**📄 {file['file_name']}**")
                            st.caption(f"النوع: {file['file_type']}")
                        with col_size:
                            st.write("**الحجم:**")
                            st.caption(f"{file['file_size'] / (1024 * 1024):.2f} MB")
                        with col_date:
                            st.write("**التاريخ:**")
                            st.caption(file['created_at'][:10] if file['created_at'] else 'غير معروف')
                        with col_actions:
                            if st.button("📥 تحميل", key=f"dl_{file['id']}", use_container_width=True):
                                with st.spinner("جاري التحميل..."):
                                    file_data = download_file(file['file_path'])
                                    if file_data:
                                        st.download_button("⬇️ اضغط للتحميل", data=file_data, file_name=file['file_name'], mime=file['file_type'], key=f"dl_c_{file['id']}")
                                    else:
                                        st.error("⚠️ الملف غير موجود")
                            
                            if st.button("🗑️ حذف", key=f"del_{file['id']}", use_container_width=True):
                                with st.spinner("جاري الحذف..."):
                                    success, errors = delete_file(file['id'], file['file_path'])
                                    if success:
                                        st.success("✅ تم الحذف بنجاح!")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ فشل الحذف: {' | '.join(errors)}")
                        st.markdown("---")

        # ==========================================
        # === تبويب فهم البيانات (المكتمل بالنقطة 3.5) ===
        # ==========================================
        with tab_eda:
            st.subheader("🔍 فهم البيانات (Data Understanding)")
            st.info("📋 نظرة عامة على البيانات قبل عملية التنظيف والإعداد للتحليل.")
            
            user_files = get_user_files(st.session_state.user_id)
            
            if len(user_files) == 0:
                st.warning("⚠️ لا توجد ملفات للتحليل. ارفع ملفاً أولاً.")
            else:
                file_options = {f["file_name"]: f for f in user_files}
                selected_file_name = st.selectbox("اختر الملف المراد تحليله:", list(file_options.keys()))
                
                if selected_file_name:
                    selected_file = file_options[selected_file_name]
                    
                    with st.spinner("جاري تحميل وقراءة البيانات..."):
                        file_bytes = download_file(selected_file['file_path'])
                        
                        if file_bytes:
                            df, error_msg = load_data_for_eda(file_bytes, selected_file_name)
                            
                            if df is not None:
                                st.success("✅ تم قراءة الملف بنجاح!")
                                
                                # القسم 1: البنية العامة
                                st.markdown("### 1️⃣ البنية العامة للداتا (Data Shape)")
                                col1, col2, col3 = st.columns(3)
                                with col1: st.metric("عدد الصفوف", f"{df.shape[0]:,}")
                                with col2: st.metric("عدد الأعمدة", df.shape[1])
                                with col3: 
                                    dup = df.duplicated().sum()
                                    st.metric("الصفوف المكررة", f"{dup} ({(dup/len(df)*100):.1f}%)")
                                st.markdown("---")
                                
                                # القسم 2: استخدام الذاكرة
                                st.markdown("### 2️⃣ استخدام الذاكرة (Memory Usage)")
                                st.metric("إجمالي الذاكرة المستخدمة", f"{df.memory_usage(deep=True).sum() / (1024 * 1024):.2f} MB")
                                st.markdown("---")
                                
                                # القسم 3: أنواع البيانات
                                st.markdown("### 3️⃣ أنواع البيانات (Data Types)")
                                dtypes_df = df.dtypes.reset_index().rename(columns={'index': 'العمود', 0: 'نوع البيانات'})
                                st.dataframe(dtypes_df, use_container_width=True, hide_index=True)
                                st.markdown("---")
                                
                                # القسم 4: الإحصائيات الوصفية
                                st.markdown("### 4️⃣ الإحصائيات الوصفية (Descriptive Statistics)")
                                numeric_cols = df.select_dtypes(include=['number']).columns
                                if len(numeric_cols) > 0:
                                    st.dataframe(df[numeric_cols].describe(), use_container_width=True)
                                else:
                                    st.info("ℹ️ لا توجد أعمدة رقمية في هذا الملف")
                                st.markdown("---")
                                
                                # القسم 5: القيم الفريدة والمفقودة
                                st.markdown("### 5️⃣ القيم الفريدة والمفقودة (Unique & Missing Values)")
                                unique_data = []
                                for col in df.columns:
                                    mode_val = df[col].mode().iloc[0] if not df[col].mode().empty else 'N/A'
                                    top_freq = df[col].value_counts().iloc[0] if not df[col].value_counts().empty else 0
                                    unique_data.append({
                                        'العمود': col,
                                        'القيم الفريدة': df[col].nunique(),
                                        'المفقودة': df[col].isnull().sum(),
                                        'نسبة المفقودة (%)': round(df[col].isnull().sum() / len(df) * 100, 2) if len(df) > 0 else 0.0,
                                        'أكثر قيمة تكراراً': str(mode_val),
                                        'نسبة التكرار (%)': round((top_freq / len(df) * 100), 2) if len(df) > 0 else 0.0
                                    })
                                st.dataframe(pd.DataFrame(unique_data), use_container_width=True, hide_index=True)
                                st.markdown("---")

                                # ==========================================
                                # القسم 6: المخططات البيانية الأولية (تنفيذ النقطة 3.5)
                                # ==========================================
                                st.markdown("### 6️⃣ المخططات البيانية الأولية (Visual Insights) - [النقطة 3.5]")
                                
                                col_chart1, col_chart2 = st.columns(2)
                                
                                with col_chart1:
                                    st.markdown("**أ. توزيع أنواع البيانات**")
                                    dtype_counts = df.dtypes.value_counts().reset_index()
                                    dtype_counts.columns = ['نوع البيانات', 'العدد']
                                    # ✅ الحل الجذري: تحويل كائنات pandas إلى نصوص عادية لتفادي خطأ JSON
                                    dtype_counts['نوع البيانات'] = dtype_counts['نوع البيانات'].astype(str)
                                    
                                    fig_dtype = px.pie(dtype_counts, values='العدد', names='نوع البيانات', 
                                                       title='نسبة أنواع الأعمدة', hole=0.4)
                                    st.plotly_chart(fig_dtype, use_container_width=True)
                                
                                with col_chart2:
                                    st.markdown("**ب. خريطة القيم المفقودة**")
                                    missing_counts = df.isnull().sum().reset_index()
                                    missing_counts.columns = ['العمود', 'عدد القيم المفقودة']
                                    missing_counts = missing_counts[missing_counts['عدد القيم المفقودة'] > 0]
                                    
                                    if not missing_counts.empty:
                                        fig_missing = px.bar(missing_counts, x='العمود', y='عدد القيم المفقودة', 
                                                             title='الأعمدة التي تحتوي على قيم مفقودة', text_auto=True)
                                        st.plotly_chart(fig_missing, use_container_width=True)
                                    else:
                                        st.success("🎉 ممتاز! لا توجد أي قيم مفقودة في البيانات.")
                                
                                st.markdown("---")
                                
                                st.markdown("**ج. خريطة الارتباط (Correlation Heatmap)**")
                                numeric_df = df.select_dtypes(include=['number'])
                                if numeric_df.shape[1] > 1:
                                    corr_matrix = numeric_df.corr().round(2)
                                    fig_corr = px.imshow(corr_matrix, text_auto=True, aspect="auto", 
                                                         title='مصفوفة الارتباط بين الأعمدة الرقمية', 
                                                         color_continuous_scale='RdBu_r')
                                    st.plotly_chart(fig_corr, use_container_width=True)
                                else:
                                    st.info("ℹ️ يتطلب رسم خريطة الارتباط وجود عمودين رقميين على الأقل.")
                                
                                st.markdown("---")

                                # القسم 7: عرض البيانات مع التنقل (Pagination)
                                st.markdown("### 7️⃣ عرض البيانات (Data Preview)")
                                rows_per_page = 10
                                total_rows = len(df)
                                total_pages = max(1, (total_rows // rows_per_page) + (1 if total_rows % rows_per_page > 0 else 0))
                                
                                if 'current_page' not in st.session_state or 'current_file' not in st.session_state:
                                    st.session_state.current_page = 1
                                    st.session_state.current_file = selected_file_name
                                elif st.session_state.current_file != selected_file_name:
                                    st.session_state.current_page = 1
                                    st.session_state.current_file = selected_file_name
                                
                                if st.session_state.current_page > total_pages: st.session_state.current_page = total_pages
                                if st.session_state.current_page < 1: st.session_state.current_page = 1
                                
                                col_nav1, col_nav2, col_nav3 = st.columns([1, 3, 1])
                                with col_nav1:
                                    if st.button("⬅️ السابق", use_container_width=True, disabled=st.session_state.current_page <= 1, key="btn_prev"):
                                        st.session_state.current_page -= 1
                                with col_nav2:
                                    selected_page = st.selectbox("انتقل إلى صفحة:", range(1, total_pages + 1), index=st.session_state.current_page - 1, key="page_selector", label_visibility="collapsed")
                                    if selected_page != st.session_state.current_page:
                                        st.session_state.current_page = selected_page
                                with col_nav3:
                                    if st.button("التالي ➡️", use_container_width=True, disabled=st.session_state.current_page >= total_pages, key="btn_next"):
                                        st.session_state.current_page += 1
                                
                                start_row = (st.session_state.current_page - 1) * rows_per_page
                                end_row = min(start_row + rows_per_page, total_rows)
                                st.info(f"📊 عرض الصفوف {start_row + 1:,} إلى {end_row:,} من أصل {total_rows:,} (صفحة {st.session_state.current_page} من {total_pages})")
                                st.dataframe(df.iloc[start_row:end_row], use_container_width=True)
                                
                            else:
                                st.error(f"❌ {error_msg}")
                        else:
                            st.error("❌ فشل تحميل الملف من التخزين.")
    
    else:
        st.title("منصة التحليل الاستكشافي الآلي 🔐")
        tab1, tab2 = st.tabs(["تسجيل الدخول", "إنشاء حساب جديد"])
        with tab1:
            email = st.text_input("البريد الإلكتروني", key="login_email")
            password = st.text_input("كلمة المرور", type="password", key="login_password")
            if st.button("دخول"):
                if email and password: login(email, password)
                else: st.warning("الرجاء إدخال البريد الإلكتروني وكلمة المرور.")
        with tab2:
            new_email = st.text_input("البريد الإلكتروني", key="signup_email")
            new_password = st.text_input("كلمة المرور", type="password", key="signup_password")
            confirm_password = st.text_input("تأكيد كلمة المرور", type="password", key="signup_confirm_password")
            if st.button("إنشاء الحساب"):
                if new_email and new_password and confirm_password:
                    if new_password == confirm_password: 
                        try:
                            supabase.auth.sign_up({"email": new_email, "password": new_password})
                            st.success("تم إنشاء الحساب بنجاح!")
                        except Exception as e: st.error(f"خطأ: {e}")
                    else: st.error("كلمتا المرور غير متطابقتين.")
                else: st.warning("الرجاء ملء جميع الحقول.")

if __name__ == "__main__":
    main()