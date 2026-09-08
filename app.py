import streamlit as st
from supabase import create_client, Client
import socket
import uuid
import pandas as pd
import numpy as np
import io
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import re
from datetime import datetime
from scipy import stats

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

# ==========================================
# ✅ إصلاح 1: دالة محسّنة لتحويل النطاقات الرقمية
# ==========================================
def parse_days_lost_range(value):
    """
    تحويل نطاق الأيام لمتوسط رقمي صحيح بدقة 100%
    الإصلاح: استخدام re.search بدلاً من re.match للتعامل مع المسافات والأحرف الزائدة
    """
    if pd.isna(value) or value == '' or str(value).strip().upper() in ['N/A', 'NA', 'NULL', 'NONE']:
        return np.nan
    
    value_str = str(value).strip()
    
    # حالة "(0) Day" أو "(0) Days"
    match_single = re.search(r'\((\d+(?:\.\d+)?)\)\s*Days?', value_str, re.IGNORECASE)
    if match_single:
        return round(float(match_single.group(1)), 2)
    
    # حالة "(0.5-1) Day" أو "(3.5-4) Days" - حساب المتوسط بدقة
    match_range = re.search(r'\((\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\)\s*Days?', value_str, re.IGNORECASE)
    if match_range:
        low = float(match_range.group(1))
        high = float(match_range.group(2))
        midpoint = (low + high) / 2.0
        return round(midpoint, 3)  # 3 decimal places for precision
    
    return np.nan

# ==========================================
# ✅ دالة ذكية لتحويل الفئات العمرية
# ==========================================
def convert_age_group_to_ordinal(value):
    """
    تحويل الفئات العمرية لأرقام ترتيبية دون تدمير النص الأصلي
    """
    if pd.isna(value) or value == '' or str(value).strip().upper() in ['N/A', 'NA', 'NULL', 'NONE']:
        return np.nan
    
    value_str = str(value).strip()
    
    age_mapping = {
        '18-24': 1,
        '25-34': 2,
        '35-49': 3,
        '50+': 4
    }
    
    return age_mapping.get(value_str, np.nan)

# ==========================================
# ✅ إصلاح 2: دالة محسّنة لخط أنابيب التنظيف التلقائي
# ==========================================
def auto_clean_pipeline(df, remove_duplicates=False, clean_columns=True, convert_numeric=True, convert_dates=True):
    report = {
        "original_rows": df.shape[0],
        "original_cols": df.shape[1],
        "duplicates_removed": 0,
        "columns_cleaned": 0,
        "numeric_conversions": 0,
        "date_conversions": 0,
        "na_values_converted": 0,
        "empty_rows_dropped": 0,
        "special_conversions": []
    }
    
    df_clean = df.copy()
    
    # ✅ إصلاح 3: تحويل قيم N/A و NA و NULL إلى NaN قبل أي معالجة
    na_values = ['N/A', 'NA', 'NULL', 'NONE', 'n/a', 'na', 'null', 'none', 'N/a', 'Na']
    initial_na_count = df_clean.isin(na_values).sum().sum()
    df_clean = df_clean.replace(na_values, np.nan)
    report["na_values_converted"] = int(initial_na_count)
    
    # ✅ إصلاح 4: حذف الصفوف الفارغة تماماً أو التي تحتوي على أكثر من 70% بيانات مفقودة
    # هذا يمنع ظهور قيم وهمية مثل 512.5 في نهاية الملف
    initial_len = len(df_clean)
    df_clean = df_clean.dropna(how='all')  # حذف الصفوف الفارغة تماماً
    df_clean = df_clean.dropna(thresh=int(df_clean.shape[1] * 0.3))  # الإبقاء على الصفوف التي تحتوي على 30% على الأقل من البيانات
    report["empty_rows_dropped"] = initial_len - len(df_clean)
    
    # ✅ إصلاح 5: إزالة التكرارات بشكل نهائي وشامل
    if remove_duplicates:
        before_dup = len(df_clean)
        df_clean = df_clean.drop_duplicates()  # إزالة التكرارات من جميع الأعمدة
        report["duplicates_removed"] = before_dup - len(df_clean)
    
    if clean_columns:
        new_columns = {}
        for col in df_clean.columns:
            new_col = str(col).strip().lower().replace(" ", "_").replace("-", "_")
            if new_col != col:
                new_columns[col] = new_col
                report["columns_cleaned"] += 1
        df_clean = df_clean.rename(columns=new_columns)
    
    # ✅ معالجة خاصة للأعمدة المعروفة
    if 'days_lost' in df_clean.columns:
        try:
            df_clean['days_lost'] = df_clean['days_lost'].apply(parse_days_lost_range)
            report["special_conversions"].append("days_lost: تم تحويل النطاقات إلى متوسطات رقمية دقيقة")
        except Exception as e:
            report["special_conversions"].append(f"days_lost: فشل التحويل ({str(e)})")
    
    if 'age_group' in df_clean.columns:
        try:
            df_clean['age_group_ordinal'] = df_clean['age_group'].apply(convert_age_group_to_ordinal)
            report["special_conversions"].append("age_group: تم إنشاء عمود ترتيبي (age_group_ordinal) مع الحفاظ على النص الأصلي")
        except Exception as e:
            report["special_conversions"].append(f"age_group: فشل التحويل ({str(e)})")
    
    if convert_numeric:
        for col in df_clean.columns:
            # ✅ تخطي الأعمدة المحمية
            if col in ['days_lost', 'age_group', 'age_group_ordinal']:
                continue
            
            if df_clean[col].dtype == 'object':
                sample_values = df_clean[col].dropna().head(30).astype(str)
                has_ranges = sample_values.str.contains(r'[\-\(\)]', regex=True).any()
                has_text = sample_values.str.contains(r'[a-zA-Z]', regex=True).any()
                
                if has_ranges or has_text:
                    continue
                
                try:
                    original_na_count = df_clean[col].isna().sum()
                    df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce')
                    new_na_count = df_clean[col].isna().sum()
                    
                    if new_na_count <= original_na_count + (len(df_clean) * 0.1):
                        report["numeric_conversions"] += 1
                except:
                    pass
    
    if convert_dates:
        for col in df_clean.columns:
            if 'date' in col or 'time' in col:
                try:
                    df_clean[col] = pd.to_datetime(df_clean[col], errors='coerce')
                    report["date_conversions"] += 1
                except:
                    pass
    
    report["final_rows"] = df_clean.shape[0]
    report["final_cols"] = df_clean.shape[1]
    
    return df_clean, report

# ==========================================
# دالة معالجة القيم المفقودة (4.2)
# ==========================================
def handle_missing_values(df, strategy='auto', constant_value=None):
    report = {
        "total_missing_before": int(df.isnull().sum().sum()),
        "columns_affected": 0,
        "strategy_used": strategy,
        "numeric_cols": 0,
        "categorical_cols": 0,
        "datetime_cols": 0,
        "details": []
    }
    
    df_clean = df.copy()
    
    for col in df_clean.columns:
        missing_count = df_clean[col].isnull().sum()
        if missing_count > 0:
            report["columns_affected"] += 1
            
            if df_clean[col].dtype in ['float64', 'int64']:
                col_type = 'numeric'
                report["numeric_cols"] += 1
            elif pd.api.types.is_datetime64_any_dtype(df_clean[col]):
                col_type = 'datetime'
                report["datetime_cols"] += 1
            else:
                col_type = 'categorical'
                report["categorical_cols"] += 1
            
            if strategy == 'auto':
                if col_type == 'numeric':
                    actual_strategy = 'median'
                elif col_type == 'datetime':
                    actual_strategy = 'ffill'
                else:
                    actual_strategy = 'mode'
            else:
                actual_strategy = strategy
            
            detail = {
                'column': col,
                'type': col_type,
                'missing': int(missing_count),
                'strategy': actual_strategy,
                'value_used': None
            }
            
            try:
                if actual_strategy == 'mean' and col_type == 'numeric':
                    fill_value = df_clean[col].mean()
                    df_clean[col] = df_clean[col].fillna(fill_value)
                    detail['value_used'] = round(fill_value, 2)
                elif actual_strategy == 'median' and col_type == 'numeric':
                    fill_value = df_clean[col].median()
                    df_clean[col] = df_clean[col].fillna(fill_value)
                    detail['value_used'] = round(fill_value, 2)
                elif actual_strategy == 'mode':
                    mode_val = df_clean[col].mode()
                    if not mode_val.empty:
                        fill_value = mode_val.iloc[0]
                        df_clean[col] = df_clean[col].fillna(fill_value)
                        detail['value_used'] = str(fill_value)
                elif actual_strategy == 'ffill':
                    df_clean[col] = df_clean[col].ffill()
                    detail['value_used'] = 'القيمة السابقة'
                elif actual_strategy == 'bfill':
                    df_clean[col] = df_clean[col].bfill()
                    detail['value_used'] = 'القيمة التالية'
                elif actual_strategy == 'interpolate' and col_type == 'numeric':
                    df_clean[col] = df_clean[col].interpolate(method='linear')
                    detail['value_used'] = 'استيفاء خطي'
                elif actual_strategy == 'constant':
                    fill_value = constant_value if constant_value is not None else 'N/A'
                    df_clean[col] = df_clean[col].fillna(fill_value)
                    detail['value_used'] = str(fill_value)
                elif actual_strategy == 'drop':
                    rows_before = len(df_clean)
                    df_clean = df_clean.dropna(subset=[col])
                    detail['rows_dropped'] = rows_before - len(df_clean)
                    detail['value_used'] = 'حذف الصفوف'
                else:
                    mode_val = df_clean[col].mode()
                    if not mode_val.empty:
                        fill_value = mode_val.iloc[0]
                        df_clean[col] = df_clean[col].fillna(fill_value)
                        detail['value_used'] = str(fill_value)
                
                report["details"].append(detail)
                
            except Exception as e:
                report["details"].append({
                    'column': col,
                    'type': col_type,
                    'missing': int(missing_count),
                    'strategy': actual_strategy,
                    'error': str(e)
                })
    
    report["total_missing_after"] = int(df_clean.isnull().sum().sum())
    report["missing_removed"] = report["total_missing_before"] - report["total_missing_after"]
    
    return df_clean, report

# ==========================================
# دالة معالجة التكرارات (4.2)
# ==========================================
def handle_duplicates(df, subset=None):
    report = {
        "total_duplicates": int(df.duplicated(subset=subset).sum()),
        "subset_used": subset if subset else 'all_columns'
    }
    
    df_clean = df.drop_duplicates(subset=subset)
    report["duplicates_removed"] = report["total_duplicates"]
    report["final_rows"] = df_clean.shape[0]
    
    return df_clean, report

# ==========================================
# دالة تصحيح أنواع البيانات (4.3) - مُحسّنة
# ==========================================
def fix_data_types(df):
    report = {
        "numeric_converted": 0,
        "datetime_converted": 0,
        "category_converted": 0,
        "details": []
    }
    
    df_fixed = df.copy()
    
    for col in df_fixed.columns:
        detail = {'column': col, 'original_type': str(df_fixed[col].dtype), 'action': 'none'}
        
        # ✅ تخطي الأعمدة الخاصة
        if col in ['days_lost', 'age_group', 'age_group_ordinal']:
            continue
        
        if df_fixed[col].dtype == 'object':
            # ✅ التحقق من وجود نطاقات أو فئات
            sample_values = df_fixed[col].dropna().head(30).astype(str)
            has_ranges = sample_values.str.contains(r'[\-\(\)]', regex=True).any()
            has_text = sample_values.str.contains(r'[a-zA-Z]', regex=True).any()
            
            if has_ranges or has_text:
                detail['action'] = 'skipped_categorical'
                report["details"].append(detail)
                continue
            
            numeric_try = pd.to_numeric(df_fixed[col], errors='coerce')
            if numeric_try.notna().sum() > len(df_fixed) * 0.8:
                df_fixed[col] = numeric_try
                report["numeric_converted"] += 1
                detail['action'] = 'converted_to_numeric'
                detail['new_type'] = 'numeric'
                detail['success_rate'] = f"{(numeric_try.notna().sum() / len(df_fixed) * 100):.1f}%"
        
        if df_fixed[col].dtype == 'object' and detail['action'] == 'none':
            try:
                datetime_try = pd.to_datetime(df_fixed[col], infer_datetime_format=True, errors='coerce')
                if datetime_try.notna().sum() > len(df_fixed) * 0.5:
                    df_fixed[col] = datetime_try
                    report["datetime_converted"] += 1
                    detail['action'] = 'converted_to_datetime'
                    detail['new_type'] = 'datetime'
                    detail['success_rate'] = f"{(datetime_try.notna().sum() / len(df_fixed) * 100):.1f}%"
            except:
                pass
        
        if df_fixed[col].dtype == 'object' and detail['action'] == 'none':
            if df_fixed[col].nunique() < 20:
                df_fixed[col] = df_fixed[col].astype('category')
                report["category_converted"] += 1
                detail['action'] = 'converted_to_category'
                detail['new_type'] = 'category'
                detail['unique_values'] = df_fixed[col].nunique()
        
        report["details"].append(detail)
    
    return df_fixed, report

# ==========================================
# دالة معالجة القيم المتطرفة (4.3)
# ==========================================
def handle_outliers(df, method='iqr', threshold=1.5, action='cap'):
    report = {
        "method_used": method,
        "threshold": threshold,
        "action_used": action,
        "total_outliers_found": 0,
        "total_outliers_handled": 0,
        "columns_affected": 0,
        "details": []
    }
    
    df_clean = df.copy()
    numeric_cols = df_clean.select_dtypes(include=['number']).columns
    
    for col in numeric_cols:
        # ✅ تخطي الأعمدة الترتيبية
        if col == 'age_group_ordinal':
            continue
            
        outliers_count = 0
        outlier_indices = []
        
        if method == 'iqr':
            Q1 = df_clean[col].quantile(0.25)
            Q3 = df_clean[col].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - threshold * IQR
            upper_bound = Q3 + threshold * IQR
            
            outlier_mask = (df_clean[col] < lower_bound) | (df_clean[col] > upper_bound)
            outliers_count = int(outlier_mask.sum())
            outlier_indices = df_clean[outlier_mask].index.tolist()
            
            detail = {
                'column': col, 'method': 'IQR', 'Q1': round(Q1, 2), 'Q3': round(Q3, 2),
                'IQR': round(IQR, 2), 'lower_bound': round(lower_bound, 2), 'upper_bound': round(upper_bound, 2),
                'outliers_count': int(outliers_count), 'outliers_percentage': round((outliers_count / len(df_clean) * 100), 2)
            }
        elif method == 'zscore':
            z_scores = np.abs(stats.zscore(df_clean[col].dropna()))
            outlier_mask = z_scores > threshold
            outliers_count = int(outlier_mask.sum())
            outlier_indices = df_clean[col].dropna()[outlier_mask].index.tolist()
            
            detail = {
                'column': col, 'method': 'Z-Score', 'threshold': threshold,
                'mean': round(df_clean[col].mean(), 2), 'std': round(df_clean[col].std(), 2),
                'outliers_count': int(outliers_count), 'outliers_percentage': round((outliers_count / len(df_clean) * 100), 2)
            }
        
        if outliers_count > 0:
            report["columns_affected"] += 1
            report["total_outliers_found"] += outliers_count
            
            if action == 'remove':
                df_clean = df_clean.drop(outlier_indices)
                detail['action'] = 'removed'
                detail['rows_removed'] = int(outliers_count)
            elif action == 'cap':
                if method == 'iqr':
                    df_clean.loc[df_clean[col] < lower_bound, col] = lower_bound
                    df_clean.loc[df_clean[col] > upper_bound, col] = upper_bound
                detail['action'] = 'capped'
                detail['lower_bound'] = round(lower_bound, 2)
                detail['upper_bound'] = round(upper_bound, 2)
            elif action == 'median':
                median_val = df_clean[col].median()
                df_clean.loc[outlier_indices, col] = median_val
                detail['action'] = 'replaced_with_median'
                detail['median_value'] = round(median_val, 2)
            
            report["total_outliers_handled"] += outliers_count
        
        report["details"].append(detail)
    
    report["final_rows"] = len(df_clean)
    report["rows_removed"] = len(df) - len(df_clean)
    
    return df_clean, report

# ==========================================
# دالة توحيد التنسيقات والتشفير (4.4)
# ==========================================
def standardize_formats(df, text_case='keep', fix_encoding=True, standardize_dates=True):
    report = {
        "text_columns_processed": 0,
        "date_columns_processed": 0,
        "encoding_fixed": 0,
        "details": []
    }
    
    df_std = df.copy()
    
    for col in df_std.columns:
        detail = {'column': col, 'original_dtype': str(df_std[col].dtype), 'actions': []}
        
        # 1. توحيد النصوص وإصلاح الترميز
        if df_std[col].dtype == 'object' or str(df_std[col].dtype) == 'string':
            actions_taken = False
            
            if fix_encoding:
                try:
                    df_std[col] = df_std[col].apply(
                        lambda x: x.encode('utf-8', errors='ignore').decode('utf-8').strip() if isinstance(x, str) else x
                    )
                    actions_taken = True
                except:
                    pass
            
            if text_case != 'keep':
                try:
                    if text_case == 'lower':
                        df_std[col] = df_std[col].astype(str).str.lower().str.strip()
                    elif text_case == 'upper':
                        df_std[col] = df_std[col].astype(str).str.upper().str.strip()
                    elif text_case == 'title':
                        df_std[col] = df_std[col].astype(str).str.title().str.strip()
                    actions_taken = True
                except:
                    pass
            
            try:
                df_std[col] = df_std[col].astype(str).str.replace(r'\s+', ' ', regex=True)
            except:
                pass
                
            if actions_taken:
                detail['actions'].append(f'text_{text_case}_and_encoding_fixed')
                report["text_columns_processed"] += 1

        # 2. توحيد التواريخ
        if standardize_dates and pd.api.types.is_datetime64_any_dtype(df_std[col]):
            try:
                df_std[col] = pd.to_datetime(df_std[col], errors='coerce').dt.strftime('%Y-%m-%d')
                detail['actions'].append('datetime_standardized_to_YYYY-MM-DD')
                report["date_columns_processed"] += 1
            except:
                pass
        
        if detail['actions']:
            report["details"].append(detail)
            
    return df_std, report

# ==========================================
# ✅ إصلاح 4: دالة محسّنة للتحقق من جودة البيانات
# ==========================================
def validate_cleaned_data(df):
    issues = []
    warnings = []
    info = []
    
    total_nulls = df.isnull().sum().sum()
    if total_nulls > 0:
        issues.append(f"لا تزال هناك {total_nulls} قيم مفقودة في البيانات")
        nulls_per_col = df.isnull().sum()
        for col, count in nulls_per_col[nulls_per_col > 0].items():
            warnings.append(f"العمود '{col}' يحتوي على {count} قيمة مفقودة")
    else:
        info.append("لا توجد قيم مفقودة")
    
    duplicates = df.duplicated().sum()
    if duplicates > 0:
        warnings.append(f"يوجد {duplicates} صف مكرر")
    else:
        info.append("لا توجد صفوف مكررة")
    
    # ✅ التحقق من days_lost
    if 'days_lost' in df.columns:
        days_lost_values = df['days_lost'].dropna()
        if len(days_lost_values) > 0:
            max_days = days_lost_values.max()
            min_days = days_lost_values.min()
            if max_days > 10:
                warnings.append(f"قيمة days_lost غير منطقية: {max_days} (أقصى قيمة متوقعة: 5)")
            if min_days < 0:
                warnings.append(f"قيمة days_lost سالبة: {min_days}")
    
    # ✅ التحقق من incident_cost
    if 'incident_cost' in df.columns:
        cost_values = df['incident_cost'].dropna()
        if len(cost_values) > 0:
            # التحقق من القيم المتكررة بشكل مفرط
            value_counts = cost_values.value_counts()
            if len(value_counts) > 0:
                most_common_value = value_counts.index[0]
                most_common_count = value_counts.iloc[0]
                if most_common_count > len(df) * 0.1:  # أكثر من 10% من البيانات
                    warnings.append(f"قيمة incident_cost تتكرر بشكل مفرط: {most_common_value} ({most_common_count} مرة)")
    
    numeric_cols = df.select_dtypes(include=['number']).columns
    outlier_info = {}
    for col in numeric_cols:
        if col == 'age_group_ordinal':
            continue
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        outliers = df[(df[col] < Q1 - 1.5*IQR) | (df[col] > Q3 + 1.5*IQR)]
        if len(outliers) > 0:
            outlier_info[col] = len(outliers)
    
    if outlier_info:
        warning_msg = "تم اكتشاف قيم متطرفة في الأعمدة التالية:\n"
        for col, count in outlier_info.items():
            warning_msg += f"  - {col}: {count} قيمة متطرفة\n"
        warnings.append(warning_msg.strip())
    else:
        info.append("لا توجد قيم متطرفة واضحة")
    
    info.append(f"إجمالي الصفوف: {len(df):,}")
    info.append(f"إجمالي الأعمدة: {df.shape[1]}")
    info.append(f"الأعمدة الرقمية: {len(numeric_cols)}")
    
    return {
        'issues': issues,
        'warnings': warnings,
        'info': info,
        'is_valid': len(issues) == 0
    }

# --- واجهة المستخدم ---
def main():
    if st.session_state.logged_in:
        st.title(f"مرحباً بك، {st.session_state.user_email} 👋")
        
        tab_home, tab_upload, tab_files, tab_eda, tab_cleaning = st.tabs([
            "🏠 الرئيسية", "📤 رفع الملفات", "📁 ملفاتي", "🔍 فهم البيانات", "🧹 تنظيف البيانات"
        ])
        
        with tab_home:
            st.write("أنت الآن في الصفحة الرئيسية لمنصة التحليل الاستكشافي.")
            st.write("️ المشروع قيد التطوير، سيتم إضافة صفحات التحليل قريباً!")
            if st.button("تسجيل الخروج"):
                logout()
        
        with tab_upload:
            st.subheader("📤 رفع ملف بيانات جديد")
            st.info("**الأنواع المسموحة:** CSV, Excel, JSON, TSV, Parquet | **الحد الأقصى:** 10 ميجابايت")
            uploaded_file = st.file_uploader("اختر ملفاً للرفع", type=['csv', 'xls', 'xlsx', 'json', 'tsv', 'parquet'])
            
            if uploaded_file is not None:
                if st.button(" رفع الملف", type="primary"):
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
                                    st.warning(f"️ فشل حفظ البيانات: {meta_result}")
                            else:
                                st.error(f"❌ فشل الرفع: {result}")
        
        with tab_files:
            st.subheader(" ملفاتي المرفوعة")
            if st.button(" تحديث القائمة"):
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
                            st.write(f"** {file['file_name']}**")
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
                                        st.error("️ الملف غير موجود")
                            
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
        # === تبويب فهم البيانات ===
        # ==========================================
        with tab_eda:
            st.subheader("🔍 فهم البيانات (Data Understanding)")
            st.info(" نظرة عامة على البيانات قبل عملية التنظيف والإعداد للتحليل.")
            
            user_files = get_user_files(st.session_state.user_id)
            
            if len(user_files) == 0:
                st.warning("️ لا توجد ملفات للتحليل. ارفع ملفاً أولاً.")
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
                                
                                st.markdown("### 1️ البنية العامة للداتا (Data Shape)")
                                col1, col2, col3 = st.columns(3)
                                with col1: st.metric("عدد الصفوف", f"{df.shape[0]:,}")
                                with col2: st.metric("عدد الأعمدة", df.shape[1])
                                with col3: 
                                    dup = df.duplicated().sum()
                                    st.metric("الصفوف المكررة", f"{dup} ({(dup/len(df)*100):.1f}%)")
                                st.markdown("---")
                                
                                st.markdown("### 2️⃣ استخدام الذاكرة (Memory Usage)")
                                st.metric("إجمالي الذاكرة المستخدمة", f"{df.memory_usage(deep=True).sum() / (1024 * 1024):.2f} MB")
                                st.markdown("---")
                                
                                st.markdown("### 3️ أنواع البيانات (Data Types)")
                                dtypes_df = df.dtypes.reset_index().rename(columns={'index': 'العمود', 0: 'نوع البيانات'})
                                st.dataframe(dtypes_df, use_container_width=True, hide_index=True)
                                st.markdown("---")
                                
                                st.markdown("### 4️⃣ الإحصائيات الوصفية (Descriptive Statistics)")
                                numeric_cols = df.select_dtypes(include=['number']).columns
                                if len(numeric_cols) > 0:
                                    st.dataframe(df[numeric_cols].describe(), use_container_width=True)
                                else:
                                    st.info("ℹ️ لا توجد أعمدة رقمية في هذا الملف")
                                st.markdown("---")
                                
                                st.markdown("### 5️ القيم الفريدة والمفقودة (Unique & Missing Values)")
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

                                st.markdown("### 6️⃣ المخططات البيانية الأولية (Visual Insights)")
                                col_chart1, col_chart2 = st.columns(2)
                                
                                with col_chart1:
                                    st.markdown("**أ. توزيع أنواع البيانات**")
                                    dtype_counts = df.dtypes.value_counts().reset_index()
                                    dtype_counts.columns = ['نوع البيانات', 'العدد']
                                    dtype_counts['نوع البيانات'] = dtype_counts['نوع البيانات'].astype(str)
                                    fig_dtype = px.pie(dtype_counts, values='العدد', names='نوع البيانات', title='نسبة أنواع الأعمدة', hole=0.4)
                                    st.plotly_chart(fig_dtype, use_container_width=True)
                                
                                with col_chart2:
                                    st.markdown("**ب. خريطة القيم المفقودة**")
                                    missing_counts = df.isnull().sum().reset_index()
                                    missing_counts.columns = ['العمود', 'عدد القيم المفقودة']
                                    missing_counts = missing_counts[missing_counts['عدد القيم المفقودة'] > 0]
                                    if not missing_counts.empty:
                                        fig_missing = px.bar(missing_counts, x='العمود', y='عدد القيم المفقودة', title='الأعمدة التي تحتوي على قيم مفقودة', text_auto=True)
                                        st.plotly_chart(fig_missing, use_container_width=True)
                                    else:
                                        st.success("🎉 ممتاز! لا توجد أي قيم مفقودة في البيانات.")
                                st.markdown("---")
                                
                                st.markdown("**ج. خريطة الارتباط (Correlation Heatmap)**")
                                numeric_df = df.select_dtypes(include=['number'])
                                if numeric_df.shape[1] > 1:
                                    corr_matrix = numeric_df.corr().round(2)
                                    fig_corr = px.imshow(corr_matrix, text_auto=True, aspect="auto", title='مصفوفة الارتباط بين الأعمدة الرقمية', color_continuous_scale='RdBu_r')
                                    st.plotly_chart(fig_corr, use_container_width=True)
                                else:
                                    st.info("ℹ️ يتطلب رسم خريطة الارتباط وجود عمودين رقميين على الأقل.")
                                st.markdown("---")

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
                                
                                if st.session_state.current_page > total_pages:
                                    st.session_state.current_page = total_pages
                                if st.session_state.current_page < 1:
                                    st.session_state.current_page = 1
                                
                                st.markdown("**🔍 أدوات التنقل:**")
                                col_ctrl1, col_ctrl2, col_ctrl3, col_ctrl4, col_ctrl5 = st.columns([1, 1, 2, 1, 1])
                                
                                with col_ctrl1:
                                    if st.button("⏮️ الأولى", use_container_width=True, key="eda_first_page"):
                                        st.session_state.current_page = 1
                                with col_ctrl2:
                                    if st.button("⬅️ السابق", use_container_width=True, disabled=st.session_state.current_page <= 1, key="btn_prev"):
                                        st.session_state.current_page -= 1
                                with col_ctrl3:
                                    target_page = st.number_input("انتقل إلى صفحة:", min_value=1, max_value=total_pages, value=st.session_state.current_page, step=1, key="eda_page_input", label_visibility="collapsed")
                                    if target_page != st.session_state.current_page:
                                        st.session_state.current_page = target_page
                                with col_ctrl4:
                                    if st.button("التالي ️", use_container_width=True, disabled=st.session_state.current_page >= total_pages, key="btn_next"):
                                        st.session_state.current_page += 1
                                with col_ctrl5:
                                    if st.button("️ الأخيرة", use_container_width=True, key="eda_last_page"):
                                        st.session_state.current_page = total_pages
                                
                                start_row = (st.session_state.current_page - 1) * rows_per_page
                                end_row = min(start_row + rows_per_page, total_rows)
                                st.info(f"📊 عرض الصفوف {start_row + 1:,} إلى {end_row:,} من أصل {total_rows:,} (صفحة {st.session_state.current_page} من {total_pages})")
                                st.dataframe(df.iloc[start_row:end_row], use_container_width=True)
                                
                            else:
                                st.error(f"❌ {error_msg}")
                        else:
                            st.error(" فشل تحميل الملف من التخزين.")

        # ==========================================
        # === تبويب تنظيف البيانات ===
        # ==========================================
        with tab_cleaning:
            st.subheader("🧹 تنظيف البيانات (Data Cleaning)")
            st.info(" محرك تنظيف تفاعلي: أنت تتحكم في كل خطوة!")
            
            user_files = get_user_files(st.session_state.user_id)
            
            if len(user_files) == 0:
                st.warning("⚠️ لا توجد ملفات للتنظيف. ارفع ملفاً أولاً.")
            else:
                file_options = {f["file_name"]: f for f in user_files}
                
                if 'selected_cleaning_file' not in st.session_state:
                    st.session_state.selected_cleaning_file = list(file_options.keys())[0] if file_options else None
                
                selected_file_name = st.selectbox(
                    "اختر الملف المراد تنظيفه:", 
                    list(file_options.keys()),
                    key="clean_file_select",
                    index=list(file_options.keys()).index(st.session_state.selected_cleaning_file) if st.session_state.selected_cleaning_file in file_options else 0
                )
                st.session_state.selected_cleaning_file = selected_file_name
                
                if selected_file_name:
                    selected_file = file_options[selected_file_name]
                    
                    if 'cleaning_df_raw' not in st.session_state or st.session_state.get('cleaning_file_name') != selected_file_name:
                        with st.spinner("جاري تحميل البيانات..."):
                            file_bytes = download_file(selected_file['file_path'])
                            if file_bytes:
                                df_raw, error_msg = load_data_for_eda(file_bytes, selected_file_name)
                                if df_raw is not None:
                                    st.session_state['cleaning_df_raw'] = df_raw
                                    st.session_state['cleaning_file_name'] = selected_file_name
                                else:
                                    st.error(f"❌ {error_msg}")
                                    st.stop()
                            else:
                                st.error("❌ فشل تحميل الملف من التخزين.")
                                st.stop()
                    
                    df_raw = st.session_state['cleaning_df_raw']
                    
                    if 'original_df' not in st.session_state or st.session_state.get('original_file') != selected_file_name:
                        st.session_state['original_df'] = df_raw.copy()
                        st.session_state['original_file'] = selected_file_name
                    
                    st.markdown("---")
                    st.markdown("###  البيانات الأصلية")
                    col1, col2, col3 = st.columns(3)
                    with col1: st.metric("عدد الصفوف", df_raw.shape[0])
                    with col2: st.metric("عدد الأعمدة", df_raw.shape[1])
                    with col3: st.metric("القيم المفقودة", df_raw.isnull().sum().sum())
                    
                    st.markdown("---")
                    st.markdown("### ⚙️ خيارات التنظيف (اختر ما تريد تطبيقه)")
                    
                    st.markdown("**🚀 الوضع السريع:**")
                    opt_auto_cleaning = st.checkbox(
                        "🚀 التنظيف التلقائي الذكي (يطبق كل العمليات دفعة واحدة)",
                        value=False,
                        help="تطبيق جميع عمليات التنظيف الأساسية بضغطة زر واحدة"
                    )
                    
                    if opt_auto_cleaning:
                        st.success("✅ تم تفعيل التنظيف التلقائي! سيتم تطبيق:")
                        st.write("- تحويل قيم N/A إلى NaN")
                        st.write("- حذف الصفوف الفارغة أو التالفة")
                        st.write("- إزالة الصفوف المكررة")
                        st.write("- تنظيف أسماء الأعمدة")
                        st.write("- تحويل الأعمدة الرقمية والتواريخ")
                        st.write("- معالجة القيم المفقودة (استراتيجية ذكية)")
                        st.write("- تصحيح أنواع البيانات")
                        st.write("- معالجة القيم المتطرفة")
                        st.write("- توحيد التنسيقات وإصلاح الترميز (UTF-8)")
                        st.write("- معالجة خاصة لـ days_lost و age_group")
                    
                    st.markdown("---")
                    st.markdown("**🔧 الوضع المتقدم (اختر العمليات يدوياً):**")
                    
                    if not opt_auto_cleaning:
                        st.markdown("**العمليات الأساسية:**")
                        col_opt1, col_opt2 = st.columns(2)
                        with col_opt1:
                            opt_remove_duplicates = st.checkbox("🔸 إزالة الصفوف المكررة", value=False)
                            opt_clean_columns = st.checkbox("🔸 تنظيف أسماء الأعمدة", value=True)
                        with col_opt2:
                            opt_convert_numeric = st.checkbox(" تحويل الأعمدة الرقمية", value=True)
                            opt_convert_dates = st.checkbox(" تحويل أعمدة التاريخ", value=True)
                        
                        st.markdown("---")
                        st.markdown("**🔹 معالجة القيم المفقودة:**")
                        opt_handle_missing = st.checkbox("🔸 معالجة القيم المفقودة", value=False)
                        if opt_handle_missing:
                            selected_strategy = st.radio(
                                "الاستراتيجية:",
                                options=["auto", "mean", "median", "mode", "ffill", "bfill", "interpolate", "constant", "drop"],
                                format_func=lambda x: {
                                    "auto": " auto - ذكية", "mean": " mean - المتوسط", "median": "📈 median - الوسيط",
                                    "mode": " mode - الأكثر تكراراً", "ffill": "⬇️ ffill - القيمة السابقة",
                                    "bfill": "⬆️ bfill - القيمة التالية", "interpolate": "📉 interpolate - استيفاء خطي",
                                    "constant": "🔢 constant - قيمة ثابتة", "drop": "️ drop - حذف الصفوف"
                                }[x],
                                index=0
                            )
                            constant_value = None
                            if selected_strategy == 'constant':
                                constant_value = st.text_input("أدخل القيمة الثابتة:", value="N/A")
                        
                        st.markdown("---")
                        st.markdown("**🔹 تصحيح أنواع البيانات (4.3):**")
                        opt_fix_types = st.checkbox("🔸 تصحيح أنواع البيانات تلقائياً", value=False, help="تحويل الأعمدة الرقمية المخزنة كنصوص، وأعمدة التاريخ، والأعمدة الفئوية")
                        
                        st.markdown("---")
                        st.markdown("**🔹 معالجة القيم المتطرفة (4.3):**")
                        opt_handle_outliers = st.checkbox("🔸 معالجة القيم المتطرفة (Outliers)", value=False, help="اكتشاف ومعالجة القيم الشاذة في الأعمدة الرقمية")
                        
                        if opt_handle_outliers:
                            col_out1, col_out2 = st.columns(2)
                            with col_out1:
                                outlier_method = st.radio("طريقة الاكتشاف:", options=["iqr", "zscore"], format_func=lambda x: {"iqr": " IQR Method", "zscore": " Z-Score Method"}[x], index=0)
                                if outlier_method == 'iqr':
                                    outlier_threshold = st.slider("معامل IQR:", 1.0, 3.0, 1.5, 0.1)
                                else:
                                    outlier_threshold = st.slider("عتبة Z-Score:", 2.0, 5.0, 3.0, 0.5)
                            with col_out2:
                                outlier_action = st.radio("إجراء المعالجة:", options=["cap", "median", "remove"], format_func=lambda x: {"cap": "🔒 استبدال بالحدود", "median": " استبدال بالوسيط", "remove": "️ حذف الصفوف"}[x], index=0)
                        
                        st.markdown("---")
                        st.markdown("** توحيد التنسيقات والتشفير (4.4):**")
                        opt_standardize_formats = st.checkbox(" توحيد تنسيقات النصوص/التواريخ وإصلاح الترميز", value=False, help="إزالة المسافات الزائدة، توحيد حالة الأحرف، وإصلاح رموز UTF-8 التالفة")
                        
                        if opt_standardize_formats:
                            col_fmt1, col_fmt2 = st.columns(2)
                            with col_fmt1:
                                text_case = st.radio("حالة الأحرف النصية:", options=["keep", "lower", "upper", "title"], format_func=lambda x: {"keep": "🔹 الإبقاء كما هي", "lower": "🔹 أحرف صغيرة (lowercase)", "upper": " أحرف كبيرة (UPPERCASE)", "title": " بداية كل كلمة كبيرة (Title Case)"}[x], index=0)
                                fix_encoding = st.checkbox("✅ إصلاح مشاكل الترميز (UTF-8 Cleanup)", value=True)
                            with col_fmt2:
                                standardize_dates = st.checkbox("✅ توحيد تنسيق التواريخ (YYYY-MM-DD)", value=True)
                    else:
                        opt_remove_duplicates = True
                        opt_clean_columns = True
                        opt_convert_numeric = True
                        opt_convert_dates = True
                        opt_handle_missing = True
                        selected_strategy = "auto"
                        constant_value = None
                        opt_fix_types = True
                        opt_handle_outliers = True
                        outlier_method = "iqr"
                        outlier_threshold = 1.5
                        outlier_action = "cap"
                        opt_standardize_formats = True
                        text_case = "keep"
                        fix_encoding = True
                        standardize_dates = True
                    
                    st.markdown("---")
                    
                    if st.button("️ معاينة التغييرات قبل التطبيق", use_container_width=True):
                        df_preview = df_raw.copy()
                        preview_report = {}
                        
                        # 1. خط أنابيب التنظيف التلقائي (مُحسّن)
                        df_preview, report_auto = auto_clean_pipeline(
                            df_preview, 
                            remove_duplicates=opt_remove_duplicates, 
                            clean_columns=opt_clean_columns, 
                            convert_numeric=opt_convert_numeric, 
                            convert_dates=opt_convert_dates
                        )
                        preview_report.update(report_auto)
                        
                        # 2. معالجة القيم المفقودة
                        if opt_handle_missing:
                            df_preview, report_missing = handle_missing_values(
                                df_preview, 
                                strategy=selected_strategy, 
                                constant_value=constant_value
                            )
                            preview_report.update(report_missing)
                        
                        # 3. تصحيح أنواع البيانات (4.3)
                        if opt_fix_types:
                            df_preview, report_types = fix_data_types(df_preview)
                            preview_report['types_report'] = report_types
                        
                        # 4. معالجة القيم المتطرفة (4.3)
                        if opt_handle_outliers:
                            df_preview, report_outliers = handle_outliers(
                                df_preview, 
                                method=outlier_method, 
                                threshold=outlier_threshold, 
                                action=outlier_action
                            )
                            preview_report['outliers_report'] = report_outliers

                        # 5. توحيد التنسيقات والتشفير (4.4)
                        if opt_standardize_formats:
                            df_preview, report_formats = standardize_formats(
                                df_preview, 
                                text_case=text_case, 
                                fix_encoding=fix_encoding, 
                                standardize_dates=standardize_dates
                            )
                            preview_report['formats_report'] = report_formats
                        
                        st.session_state['preview_df'] = df_preview
                        st.session_state['preview_report'] = preview_report
                        st.session_state['preview_options'] = {
                            'auto_cleaning': opt_auto_cleaning, 
                            'remove_duplicates': opt_remove_duplicates, 
                            'clean_columns': opt_clean_columns,
                            'convert_numeric': opt_convert_numeric, 
                            'convert_dates': opt_convert_dates, 
                            'handle_missing': opt_handle_missing,
                            'missing_strategy': selected_strategy if opt_handle_missing else None, 
                            'fix_types': opt_fix_types,
                            'handle_outliers': opt_handle_outliers, 
                            'outlier_method': outlier_method if opt_handle_outliers else None,
                            'outlier_threshold': outlier_threshold if opt_handle_outliers else None, 
                            'outlier_action': outlier_action if opt_handle_outliers else None,
                            'standardize_formats': opt_standardize_formats, 
                            'text_case': text_case if opt_standardize_formats else None,
                            'fix_encoding': fix_encoding if opt_standardize_formats else None, 
                            'standardize_dates': standardize_dates if opt_standardize_formats else None
                        }
                        st.success("✅ تم إنشاء المعاينة! راجع التغييرات أدناه.")
                    
                    if 'preview_df' in st.session_state and 'preview_report' in st.session_state:
                        st.markdown("---")
                        st.markdown("### 🔍 معاينة التغييرات المقترحة")
                        report = st.session_state['preview_report']
                        
                        # 1. جدول تفصيلي شامل
                        st.markdown("### 📋 التقرير التفصيلي للمعالجة:")
                        if 'details' in report and report['details']:
                            detail_df = pd.DataFrame(report['details'])
                            detail_df_display = detail_df.rename(columns={
                                'column': 'العمود', 
                                'type': 'النوع', 
                                'missing': 'المفقودة', 
                                'strategy': 'الاستراتيجية', 
                                'value_used': 'القيمة المستخدمة'
                            })
                            detail_df_display['النوع'] = detail_df_display['النوع'].map({
                                'numeric': 'رقمي', 
                                'categorical': 'فئوي/نصي', 
                                'datetime': 'زمني'
                            })
                            required_cols = ['العمود', 'النوع', 'المفقودة', 'الاستراتيجية', 'القيمة المستخدمة']
                            available_cols = [col for col in required_cols if col in detail_df_display.columns]
                            if available_cols:
                                st.dataframe(detail_df_display[available_cols], use_container_width=True, hide_index=True, height=300)
                            else:
                                st.warning("⚠️ لا توجد تفاصيل متاحة للعرض")
                        else:
                            st.info("ℹ️ لم يتم معالجة أي قيم مفقودة")
                        
                        # 2. تقرير تصحيح أنواع البيانات (4.3)
                        if 'types_report' in report:
                            st.markdown("---")
                            st.markdown("### 🔧 تقرير تصحيح أنواع البيانات:")
                            types_report = report['types_report']
                            col_t1, col_t2, col_t3 = st.columns(3)
                            with col_t1: st.metric("أعمدة رقمية محولة", types_report['numeric_converted'])
                            with col_t2: st.metric("أعمدة تاريخ محولة", types_report['datetime_converted'])
                            with col_t3: st.metric("أعمدة فئوية محولة", types_report['category_converted'])
                            if types_report['details']:
                                types_df = pd.DataFrame(types_report['details']).rename(columns={
                                    'column': 'العمود', 
                                    'original_type': 'النوع الأصلي', 
                                    'action': 'الإجراء', 
                                    'new_type': 'النوع الجديد'
                                })
                                st.dataframe(types_df, use_container_width=True, hide_index=True, height=200)
                        
                        # 3. تقرير القيم المتطرفة (4.3)
                        if 'outliers_report' in report:
                            st.markdown("---")
                            st.markdown("### ⚠️ تقرير القيم المتطرفة:")
                            outliers_report = report['outliers_report']
                            col_o1, col_o2, col_o3 = st.columns(3)
                            with col_o1: st.metric("إجمالي القيم المتطرفة", outliers_report['total_outliers_found'])
                            with col_o2: st.metric("تمت معالجتها", outliers_report['total_outliers_handled'])
                            with col_o3: st.metric("الأعمدة المتأثرة", outliers_report['columns_affected'])
                            st.info(f"**الطريقة:** {outliers_report['method_used'].upper()} | **العتبة:** {outliers_report['threshold']} | **الإجراء:** {outliers_report['action_used']}")
                            if outliers_report['details']:
                                outliers_df = pd.DataFrame(outliers_report['details']).rename(columns={
                                    'column': 'العمود', 
                                    'method': 'الطريقة', 
                                    'outliers_count': 'عدد المتطرفة', 
                                    'outliers_percentage': 'النسبة %', 
                                    'action': 'الإجراء'
                                })
                                st.dataframe(outliers_df, use_container_width=True, hide_index=True, height=200)

                        # 4. تقرير توحيد التنسيقات (4.4)
                        if 'formats_report' in report:
                            st.markdown("---")
                            st.markdown("### 🔤 تقرير توحيد التنسيقات والتشفير:")
                            formats_report = report['formats_report']
                            col_f1, col_f2, col_f3 = st.columns(3)
                            with col_f1: st.metric("أعمدة نصية تم تنظيفها", formats_report['text_columns_processed'])
                            with col_f2: st.metric("أعمدة تاريخ موحدة", formats_report['date_columns_processed'])
                            with col_f3: st.metric("أعمدة تم إصلاح ترميزها", formats_report['encoding_fixed'])
                            if formats_report['details']:
                                formats_df = pd.DataFrame(formats_report['details']).rename(columns={
                                    'column': 'العمود', 
                                    'original_dtype': 'النوع الأصلي', 
                                    'actions': 'الإجراءات المتخذة'
                                })
                                st.dataframe(formats_df, use_container_width=True, hide_index=True, height=200)
                        
                        # 5. إحصائيات سريعة وملخص
                        st.markdown("---")
                        st.markdown("### 📊 إحصائيات سريعة:")
                        col1, col2, col3, col4 = st.columns(4)
                        with col1: st.metric("إجمالي القيم المعالجة", f"{report.get('missing_removed', 0):,}")
                        with col2: st.metric("الأعمدة المتأثرة", report.get('columns_affected', 0))
                        with col3: st.metric("الأعمدة الرقمية", report.get('numeric_cols', 0))
                        with col4: st.metric("الأعمدة الفئوية", report.get('categorical_cols', 0))
                        
                        st.markdown("---")
                        st.markdown("### 📝 ملخص العمليات:")
                        if report.get('na_values_converted', 0) > 0:
                            st.success(f"✅ تم تحويل **{report['na_values_converted']}** قيمة N/A إلى NaN")
                        if report.get('empty_rows_dropped', 0) > 0:
                            st.success(f"✅ تم حذف **{report['empty_rows_dropped']}** صف فارغ أو تالف")
                        if report.get('duplicates_removed', 0) > 0:
                            dup_count = report['duplicates_removed']
                            dup_pct = (dup_count / df_raw.shape[0]) * 100
                            if dup_pct > 10: 
                                st.error(f" **تحذير حرج:** سيتم حذف **{dup_count}** صف مكرر (**{dup_pct:.1f}%** من بياناتك!)")
                            else: 
                                st.warning(f"⚠️ سيتم حذف **{dup_count}** صف مكرر ({dup_pct:.1f}%)")
                        if report.get('missing_removed', 0) > 0: 
                            st.info(f"ℹ️ سيتم معالجة **{report['missing_removed']}** قيمة مفقودة")
                        if report.get('columns_cleaned', 0) > 0: 
                            st.success(f"✅ سيتم تنظيف أسماء **{report['columns_cleaned']}** عمود")
                        if report.get('numeric_conversions', 0) > 0: 
                            st.success(f"✅ سيتم تحويل **{report['numeric_conversions']}** عمود إلى أرقام")
                        if 'special_conversions' in report and report['special_conversions']:
                            for conv in report['special_conversions']:
                                st.success(f"✅ {conv}")
                        if 'formats_report' in report and formats_report['text_columns_processed'] > 0:
                            st.success(f"✅ سيتم توحيد وتنظيف **{formats_report['text_columns_processed']}** عمود نصي")
                        
                        st.markdown("---")
                        
                        # 6. معاينة البيانات
                        st.markdown("### 👁️ معاينة البيانات بعد التنظيف")
                        rows_per_page = 10
                        total_rows = len(st.session_state['preview_df'])
                        total_pages = max(1, (total_rows // rows_per_page) + (1 if total_rows % rows_per_page > 0 else 0))
                        if 'cleaning_page' not in st.session_state: 
                            st.session_state.cleaning_page = 1
                        if st.session_state.cleaning_page > total_pages: 
                            st.session_state.cleaning_page = total_pages
                        if st.session_state.cleaning_page < 1: 
                            st.session_state.cleaning_page = 1
                        
                        st.markdown("**🔍 أدوات التنقل:**")
                        col_ctrl1, col_ctrl2, col_ctrl3, col_ctrl4, col_ctrl5 = st.columns([1, 1, 2, 1, 1])
                        with col_ctrl1:
                            if st.button("⏮️ الأولى", use_container_width=True, key="clean_first_page"): 
                                st.session_state.cleaning_page = 1
                        with col_ctrl2:
                            if st.button("⬅️ السابق", use_container_width=True, disabled=st.session_state.cleaning_page <= 1, key="clean_btn_prev"): 
                                st.session_state.cleaning_page -= 1
                        with col_ctrl3:
                            target_page = st.number_input("انتقل إلى صفحة:", min_value=1, max_value=total_pages, value=st.session_state.cleaning_page, step=1, key="clean_page_input", label_visibility="collapsed")
                            if target_page != st.session_state.cleaning_page: 
                                st.session_state.cleaning_page = target_page
                        with col_ctrl4:
                            if st.button("التالي ➡️", use_container_width=True, disabled=st.session_state.cleaning_page >= total_pages, key="clean_btn_next"): 
                                st.session_state.cleaning_page += 1
                        with col_ctrl5:
                            if st.button("⏭️ الأخيرة", use_container_width=True, key="clean_last_page"): 
                                st.session_state.cleaning_page = total_pages
                        
                        start_row = (st.session_state.cleaning_page - 1) * rows_per_page
                        end_row = min(start_row + rows_per_page, total_rows)
                        st.info(f"📊 عرض الصفوف {start_row + 1:,} إلى {end_row:,} من أصل {total_rows:,} (صفحة {st.session_state.cleaning_page} من {total_pages})")
                        
                        preview_df_page = st.session_state['preview_df'].iloc[start_row:end_row]
                        search_term = st.text_input("🔍 ابحث في البيانات:", placeholder="اكتب كلمة للبحث...", key="data_search")
                        if search_term:
                            mask = preview_df_page.apply(lambda row: row.astype(str).str.contains(search_term, case=False, na=False).any(), axis=1)
                            preview_df_page = preview_df_page[mask]
                            st.info(f"🔍 تم العثور على {len(preview_df_page)} نتيجة")
                        st.dataframe(preview_df_page, use_container_width=True, height=400)
                        
                        st.markdown("---")
                        
                        # 7. التحقق من جودة البيانات
                        st.markdown("### ✅ التحقق من جودة البيانات:")
                        validation_result = validate_cleaned_data(st.session_state['preview_df'])
                        if validation_result['is_valid']: 
                            st.success("✅ **البيانات جاهزة للتحليل!**")
                        else:
                            st.error("❌ **توجد مشاكل:**")
                            for issue in validation_result['issues']: 
                                st.error(f"❌ {issue}")
                        if validation_result['warnings']:
                            st.warning("⚠️ **تحذيرات:**")
                            for warning in validation_result['warnings']: 
                                st.warning(f"⚠️ {warning}")
                        if validation_result['info']:
                            st.info("📊 **معلومات:**")
                            for info_item in validation_result['info']: 
                                st.info(info_item)
                        
                        st.markdown("---")
                        
                        # 8. أزرار التطبيق
                        col_apply1, col_apply2, col_apply3 = st.columns(3)
                        with col_apply1:
                            if st.button("✅ تطبيق التغييرات نهائياً", type="primary", use_container_width=True, key="apply_cleaning"):
                                st.session_state['cleaned_df'] = st.session_state['preview_df']
                                st.session_state['cleaning_report_final'] = report
                                st.session_state['validation_result'] = validation_result
                                st.session_state['cleaning_applied'] = True
                                st.success("✅ تم تطبيق التغييرات بنجاح!")
                        with col_apply2:
                            if st.button("❌ إلغاء والعودة للخيارات", use_container_width=True, key="cancel_cleaning"):
                                if 'preview_df' in st.session_state: 
                                    del st.session_state['preview_df']
                                if 'preview_report' in st.session_state: 
                                    del st.session_state['preview_report']
                                st.rerun()
                        with col_apply3:
                            if st.session_state.get('cleaning_applied', False) and st.button("️ تراجع", use_container_width=True, key="undo_cleaning"):
                                if 'cleaned_df' in st.session_state: 
                                    del st.session_state['cleaned_df']
                                if 'cleaning_report_final' in st.session_state: 
                                    del st.session_state['cleaning_report_final']
                                if 'cleaning_applied' in st.session_state: 
                                    del st.session_state['cleaning_applied']
                                st.success("✅ تم التراجع!")
                                st.rerun()
                    
                    # عرض النتيجة بعد التطبيق
                    if st.session_state.get('cleaning_applied', False) and 'cleaned_df' in st.session_state:
                        st.markdown("---")
                        st.markdown("### ✅ التنظيف مكتمل!")
                        report = st.session_state['cleaning_report_final']
                        df_cleaned = st.session_state['cleaned_df']
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("الصفوف (قبل)", report.get('original_rows', df_raw.shape[0]))
                            st.metric("القيم المفقودة (قبل)", df_raw.isnull().sum().sum())
                        with col2:
                            st.metric("الصفوف (بعد)", report.get('final_rows', df_cleaned.shape[0]))
                            st.metric("القيم المفقودة (بعد)", df_cleaned.isnull().sum().sum())
                        
                        st.markdown("---")
                        st.markdown("### 📥 تصدير البيانات النظيفة:")
                        csv = df_cleaned.to_csv(index=False).encode('utf-8')
                        st.download_button(label=" تحميل كـ CSV", data=csv, file_name=f"cleaned_{selected_file_name}.csv", mime='text/csv', use_container_width=True)
                        
                        if 'preview_report' in st.session_state:
                            report_json = json.dumps(st.session_state['preview_report'], indent=2, default=str, ensure_ascii=False)
                            st.download_button(label="📥 تصدير تقرير التنظيف (JSON)", data=report_json, file_name=f"cleaning_report_{selected_file_name}.json", mime='application/json', use_container_width=True)
                        
                        excel_buffer = io.BytesIO()
                        df_cleaned.to_excel(excel_buffer, index=False, engine='openpyxl')
                        excel_buffer.seek(0)
                        st.download_button(label=" تحميل كـ Excel", data=excel_buffer, file_name=f"cleaned_{selected_file_name}.xlsx", mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
    
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