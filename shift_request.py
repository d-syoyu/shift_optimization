import pandas as pd
import datetime
from flask import current_app

class ShiftRequestManager:
    def __init__(self, optimizer=None):
        self.optimizer = optimizer
        self.shift_requests = []
        
    def set_optimizer(self, optimizer):
        """最適化エンジンを設定"""
        self.optimizer = optimizer
    
    def clear_requests(self):
        """すべてのシフト希望をクリア"""
        self.shift_requests = []
    
    def add_request(self, employee_id, date, shift_name=None, start_time=None, end_time=None, 
                   break_time=None, note=None, is_day_off=False):
        """シフト希望を追加"""
        # 日付をdate型に変換
        if isinstance(date, str):
            try:
                date = datetime.datetime.strptime(date, '%Y/%m/%d').date()
            except ValueError:
                try:
                    date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError(f"日付フォーマットエラー: {date}. YYYY/MM/DD または YYYY-MM-DD形式で入力してください。")
        
        # 時間を分単位に変換
        start_minutes = None
        end_minutes = None
        break_minutes = None
        
        if start_time:
            if isinstance(start_time, str):
                try:
                    h, m = map(int, start_time.split(':'))
                    start_minutes = h * 60 + m
                except (ValueError, TypeError):
                    pass
            
        if end_time:
            if isinstance(end_time, str):
                try:
                    h, m = map(int, end_time.split(':'))
                    end_minutes = h * 60 + m
                    # 終了時間が開始時間より前の場合は翌日とみなす
                    if start_minutes is not None and end_minutes < start_minutes:
                        end_minutes += 24 * 60
                except (ValueError, TypeError):
                    pass
        
        if break_time:
            if isinstance(break_time, str):
                try:
                    # 時間形式の場合
                    if ':' in break_time:
                        h, m = map(int, break_time.split(':'))
                        break_minutes = h * 60 + m
                    else:
                        # 数値のみの場合は時間とみなす
                        break_minutes = float(break_time) * 60
                except (ValueError, TypeError):
                    pass
            elif isinstance(break_time, (int, float)):
                break_minutes = break_time * 60
        
        request = {
            'employee_id': employee_id,
            'date': date,
            'shift_name': shift_name,
            'start_minutes': start_minutes,
            'end_minutes': end_minutes,
            'break_minutes': break_minutes,
            'note': note,
            'is_day_off': is_day_off
        }
        
        self.shift_requests.append(request)
        return request
    
    def import_requests_from_csv(self, file_path=None, file_content=None, encoding='utf-8-sig'):
        """CSVファイルからシフト希望をインポート"""
        try:
            if file_path:
                df = pd.read_csv(file_path, encoding=encoding)
            elif file_content:
                df = pd.read_csv(file_content, encoding=encoding)
            else:
                raise ValueError("ファイルパスまたはファイル内容を指定してください")
            
            # カラム名の正規化（全角スペースを半角に、余分なスペースを削除）
            df.columns = [col.replace('　', ' ').strip() for col in df.columns]
            
            # 必須カラムのチェック
            required_columns = ['スタッフコード', '日付']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"必須カラムがありません: {', '.join(missing_columns)}")
            
            # データをインポート
            for _, row in df.iterrows():
                employee_id = row['スタッフコード']
                date = row['日付']
                
                # 休みの判定
                is_day_off = False
                shift_name = None
                if '休み' in row and pd.notna(row['休み']):
                    is_day_off = True
                elif 'シフト名' in row and pd.notna(row['シフト名']):
                    shift_name = row['シフト名']
                
                # 時間情報の取得
                start_time = None
                end_time = None
                break_time = None
                
                if '出勤時刻' in row and pd.notna(row['出勤時刻']):
                    start_time = str(row['出勤時刻'])
                
                if '退勤時刻' in row and pd.notna(row['退勤時刻']):
                    end_time = str(row['退勤時刻'])
                
                if '休憩時間' in row and pd.notna(row['休憩時間']):
                    break_time = row['休憩時間']
                
                # 備考情報
                note = None
                if 'スタッフからの備考' in row and pd.notna(row['スタッフからの備考']):
                    note = row['スタッフからの備考']
                
                # シフト希望を追加
                self.add_request(
                    employee_id=employee_id,
                    date=date,
                    shift_name=shift_name,
                    start_time=start_time,
                    end_time=end_time,
                    break_time=break_time,
                    note=note,
                    is_day_off=is_day_off
                )
            
            return len(df)
        except Exception as e:
            current_app.logger.error(f"シフト希望インポートエラー: {str(e)}")
            raise
    
    def apply_requests_to_optimizer(self):
        """シフト希望を最適化エンジンに適用"""
        if not self.optimizer:
            raise ValueError("最適化エンジンが設定されていません")
        
        # シフト希望を適用
        for request in self.shift_requests:
            employee_id = request['employee_id']
            date = request['date']
            
            # 従業員のインデックスを取得
            employee_index = None
            for i, emp in enumerate(self.optimizer.employees):
                if emp['id'] == employee_id:
                    employee_index = i
                    break
            
            if employee_index is None:
                continue  # 従業員が見つからない場合はスキップ
            
            # 休みの希望を適用
            if request['is_day_off']:
                # 勤務不可日に追加
                if date not in self.optimizer.employees[employee_index]['unavailable_days']:
                    self.optimizer.employees[employee_index]['unavailable_days'].append(date)
            
            # シフト名による希望を適用
            elif request['shift_name']:
                shift_id = None
                
                # シフト名からシフトIDを検索
                for shift in self.optimizer.shifts:
                    if shift['name'] == request['shift_name'] or shift['name'].startswith(request['shift_name']):
                        shift_id = shift['id']
                        break
                
                if shift_id is not None:
                    # 希望シフトに追加
                    if shift_id not in self.optimizer.employees[employee_index]['preferred_shifts']:
                        self.optimizer.employees[employee_index]['preferred_shifts'].append(shift_id)
            
            # 時刻指定の希望を適用
            elif request['start_minutes'] is not None and request['end_minutes'] is not None:
                # 時刻指定シフトの場合は、最適化エンジンに新しいシフトを追加
                # このシフトは従業員専用とし、希望シフトに設定
                shift_name = f"Request_{employee_id}_{date.strftime('%Y%m%d')}"
                
                # 既存のシフトIDの最大値を取得
                max_shift_id = 0
                for shift in self.optimizer.shifts:
                    if shift['id'] > max_shift_id:
                        max_shift_id = shift['id']
                
                new_shift_id = max_shift_id + 1
                
                # 新しいシフトを追加
                self.optimizer.add_shift(
                    shift_id=new_shift_id,
                    name=shift_name,
                    start_time=request['start_minutes'],
                    end_time=request['end_minutes'],
                    required_skills=[],  # スキル要件なし
                    required_employees=1,  # 1人必要
                    is_fixed=True  # 固定シフト
                )
                
                # 希望シフトに追加
                self.optimizer.employees[employee_index]['preferred_shifts'].append(new_shift_id)
        
        return len(self.shift_requests)
