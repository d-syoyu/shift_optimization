import numpy as np
import pandas as pd
from ortools.sat.python import cp_model
import datetime

class ShiftOptimizer:
    def __init__(self):
        self.employees = []
        self.shifts = []
        self.days = []
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()
        self.solver.parameters.linearization_level = 0
        # デフォルトでは1時間のタイムリミットを設定
        self.solver.parameters.max_time_in_seconds = 3600.0
        
    def add_employee(self, employee_id, name, skills=None, max_hours_day=8, 
                    max_hours_week=40, max_consecutive_days=5, unavailable_days=None, 
                    preferred_shifts=None):
        """従業員を追加する"""
        if skills is None:
            skills = []
        if unavailable_days is None:
            unavailable_days = []
        if preferred_shifts is None:
            preferred_shifts = []
            
        employee = {
            'id': employee_id,
            'name': name,
            'skills': skills,
            'max_hours_day': max_hours_day,
            'max_hours_week': max_hours_week,
            'max_consecutive_days': max_consecutive_days,
            'unavailable_days': unavailable_days,
            'preferred_shifts': preferred_shifts
        }
        self.employees.append(employee)
        return employee
    
    def add_shift(self, shift_id, name, start_time, end_time, required_skills=None, 
                 required_employees=1, is_fixed=False):
        """シフトを追加する"""
        if required_skills is None:
            required_skills = []
            
        # 時間をHH:MM形式から分単位に変換
        if isinstance(start_time, str):
            h, m = map(int, start_time.split(':'))
            start_minutes = h * 60 + m
        else:
            start_minutes = start_time
            
        if isinstance(end_time, str):
            h, m = map(int, end_time.split(':'))
            end_minutes = h * 60 + m
        else:
            end_minutes = end_time
            
        # 終了時間が開始時間より前の場合は翌日とみなす
        if end_minutes < start_minutes:
            end_minutes += 24 * 60
            
        shift = {
            'id': shift_id,
            'name': name,
            'start_minutes': start_minutes,
            'end_minutes': end_minutes,
            'duration': end_minutes - start_minutes,
            'required_skills': required_skills,
            'required_employees': required_employees,
            'is_fixed': is_fixed
        }
        self.shifts.append(shift)
        return shift
    
    def set_schedule_period(self, start_date, end_date):
        """スケジュール期間を設定する"""
        current_date = start_date
        self.days = []
        
        while current_date <= end_date:
            self.days.append({
                'date': current_date,
                'weekday': current_date.weekday()  # 0=月曜日, 6=日曜日
            })
            current_date += datetime.timedelta(days=1)
    
    def add_avoidance_pair(self, employee1_id, employee2_id):
        """バッティング回避ペアを追加する"""
        if not hasattr(self, 'avoidance_pairs'):
            self.avoidance_pairs = []
        self.avoidance_pairs.append((employee1_id, employee2_id))
    
    def setup_model(self):
        """最適化モデルをセットアップする"""
        # 変数: employee, day, shift の組み合わせに対する割り当て (0または1)
        self.shift_vars = {}
        
        for employee in self.employees:
            for day_idx, day in enumerate(self.days):
                for shift in self.shifts:
                    var_name = f'e{employee["id"]}_d{day_idx}_s{shift["id"]}'
                    self.shift_vars[(employee["id"], day_idx, shift["id"])] = self.model.NewBoolVar(var_name)
        
        # 制約1: 各従業員は1日に最大1つのシフトのみ割り当て可能
        for employee in self.employees:
            for day_idx, _ in enumerate(self.days):
                daily_shifts = []
                for shift in self.shifts:
                    daily_shifts.append(self.shift_vars[(employee["id"], day_idx, shift["id"])])
                self.model.Add(sum(daily_shifts) <= 1)
        
        # 制約2: 各シフトには必要な人数を割り当てる（ソフト制約に変更）
        self.required_employees_violations = []
        for day_idx, _ in enumerate(self.days):
            for shift in self.shifts:
                shift_employees = []
                for employee in self.employees:
                    shift_employees.append(self.shift_vars[(employee["id"], day_idx, shift["id"])])
                
                # ソフト制約: 違反すると大きなペナルティを与える
                violation = self.model.NewIntVar(0, len(self.employees), f'violation_d{day_idx}_s{shift["id"]}')
                self.model.Add(sum(shift_employees) + violation >= shift["required_employees"])
                self.model.Add(sum(shift_employees) <= shift["required_employees"] + 2)  # 少し余裕を持たせる
                
                # 違反に大きな重みを付ける
                self.required_employees_violations.append(violation * 1000)
        
        # 制約3: スキル要件を満たす（これはハード制約のまま）
        for day_idx, _ in enumerate(self.days):
            for shift in self.shifts:
                if shift["required_skills"]:
                    for employee in self.employees:
                        has_required_skills = all(skill in employee["skills"] for skill in shift["required_skills"])
                        if not has_required_skills:
                            # 必要なスキルがない従業員はそのシフトに割り当てられない
                            self.model.Add(self.shift_vars[(employee["id"], day_idx, shift["id"])] == 0)
        
        # 制約4: 勤務不可日（ソフト制約に変更）
        self.unavailable_violations = []
        for employee in self.employees:
            for day_idx, day in enumerate(self.days):
                if day["date"] in employee["unavailable_days"]:
                    for shift in self.shifts:
                        # 勤務不可日の割り当ては避けるが、絶対に不可ではない
                        violation_var = self.shift_vars[(employee["id"], day_idx, shift["id"])]
                        self.unavailable_violations.append(violation_var * 500)  # 500は重み
        
        # 制約5: 1週間の最大勤務時間（ハード制約のまま）
        for employee in self.employees:
            max_weekly_minutes = employee["max_hours_week"] * 60
            
            for week_start in range(0, len(self.days), 7):
                week_end = min(week_start + 7, len(self.days))
                weekly_work_minutes = []
                
                for day_idx in range(week_start, week_end):
                    for shift in self.shifts:
                        work_minutes = self.shift_vars[(employee["id"], day_idx, shift["id"])] * shift["duration"]
                        weekly_work_minutes.append(work_minutes)
                
                self.model.Add(sum(weekly_work_minutes) <= max_weekly_minutes)
        
        # 制約6: 連続勤務日数の上限（ハード制約のまま）
        for employee in self.employees:
            max_consecutive = employee["max_consecutive_days"]
            
            for start_idx in range(len(self.days) - max_consecutive):
                consecutive_days = []
                
                for day_offset in range(max_consecutive + 1):
                    day_shifts = []
                    for shift in self.shifts:
                        day_shifts.append(self.shift_vars[(employee["id"], start_idx + day_offset, shift["id"])])
                    # その日に勤務するかどうか
                    consecutive_days.append(sum(day_shifts))
                
                # max_consecutive + 1日連続で勤務しないようにする
                self.model.Add(sum(consecutive_days) <= max_consecutive)
        
        # 制約7: バッティング回避（ソフト制約に変更）
        self.avoidance_violations = []
        if hasattr(self, 'avoidance_pairs'):
            for emp1_id, emp2_id in self.avoidance_pairs:
                for day_idx, _ in enumerate(self.days):
                    for shift in self.shifts:
                        # 同時勤務の回避をソフト制約に
                        violation = self.model.NewBoolVar(f'avoid_{emp1_id}_{emp2_id}_d{day_idx}_s{shift["id"]}')
                        self.model.Add(
                            self.shift_vars[(emp1_id, day_idx, shift["id"])] + 
                            self.shift_vars[(emp2_id, day_idx, shift["id"])] <= 1 + violation
                        )
                        self.avoidance_violations.append(violation * 300)  # 300は重み
        
        # 目的関数: 希望シフトへの割り当てを最大化 + 制約違反のペナルティを最小化
        preferences = []
        
        for employee in self.employees:
            for day_idx, _ in enumerate(self.days):
                for shift in self.shifts:
                    if shift["id"] in employee["preferred_shifts"]:
                        preferences.append(self.shift_vars[(employee["id"], day_idx, shift["id"])] * 10)  # 10は重み
        
        # 目的関数 = 希望シフトの割り当て - 制約違反のペナルティ
        violations = (
            self.required_employees_violations + 
            self.unavailable_violations + 
            self.avoidance_violations
        )
        
        self.model.Maximize(sum(preferences) - sum(violations))
    
    def solve(self):
        """最適化問題を解く"""
        self.setup_model()
        
        # ソルバーのパラメータを設定
        self.solver.parameters.linearization_level = 0
        self.solver.parameters.max_time_in_seconds = 60.0  # 解探索の時間制限（必要に応じて調整）
        
        # 問題の複雑さに応じてヒントを追加
        # ランダムシードの設定（異なる解を得るため）
        self.solver.parameters.random_seed = 42
        
        # より多様な解を探すための設定
        self.solver.parameters.num_search_workers = 8  # 並列ワーカー数（CPUコア数に合わせて調整）
        self.solver.parameters.log_search_progress = True  # 検索の進捗をログに出力
        
        status = self.solver.Solve(self.model)
        
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # スケジュールの解を取得
            schedule = {}
            
            for employee in self.employees:
                employee_schedule = []
                
                for day_idx, day in enumerate(self.days):
                    assigned_shift = None
                    
                    for shift in self.shifts:
                        if self.solver.Value(self.shift_vars[(employee["id"], day_idx, shift["id"])]) == 1:
                            assigned_shift = shift
                            break
                    
                    employee_schedule.append({
                        'date': day["date"],
                        'weekday': day["weekday"],
                        'shift': assigned_shift
                    })
                
                schedule[employee["id"]] = employee_schedule
            
            # 制約違反の集計
            violations_summary = {
                'required_employees_violations': sum(self.solver.Value(v) for v in self.required_employees_violations),
                'unavailable_violations': sum(self.solver.Value(v) for v in self.unavailable_violations) / 500,  # 重みで割る
                'avoidance_violations': sum(self.solver.Value(v) for v in self.avoidance_violations) / 300  # 重みで割る
            }
            
            return {
                'status': 'success',
                'schedule': schedule,
                'objective_value': self.solver.ObjectiveValue(),
                'violations': violations_summary
            }
        else:
            # 問題が解決できなかった場合のデバッグ情報
            debug_info = {
                'num_employees': len(self.employees),
                'num_shifts': len(self.shifts),
                'num_days': len(self.days),
                'status_code': status,
                'status_name': self._get_status_name(status)
            }
            
            return {
                'status': 'failed',
                'reason': f'Solver status: {status}',
                'debug_info': debug_info
            }
    
    def _get_status_name(self, status):
        """ステータスコードに対応する名前を返す"""
        if status == cp_model.OPTIMAL:
            return "OPTIMAL"
        elif status == cp_model.FEASIBLE:
            return "FEASIBLE"
        elif status == cp_model.INFEASIBLE:
            return "INFEASIBLE (制約条件を満たす解が存在しません)"
        elif status == cp_model.MODEL_INVALID:
            return "MODEL_INVALID (モデルに問題があります)"
        elif status == cp_model.UNKNOWN:
            return "UNKNOWN (時間内に解が見つかりませんでした)"
        else:
            return f"UNKNOWN_STATUS ({status})"
    
    def get_shift_table(self, result):
        """スケジュール結果をデータフレーム形式で取得"""
        if result['status'] != 'success':
            return None
            
        rows = []
        
        for emp_id, schedule in result['schedule'].items():
            employee = next(e for e in self.employees if e['id'] == emp_id)
            
            for day_data in schedule:
                row = {
                    'employee_id': emp_id,
                    'employee_name': employee['name'],
                    'date': day_data['date'],
                    'weekday': day_data['weekday'],
                    'shift_id': day_data['shift']['id'] if day_data['shift'] else None,
                    'shift_name': day_data['shift']['name'] if day_data['shift'] else 'Off',
                    'start_time': self._minutes_to_time(day_data['shift']['start_minutes']) if day_data['shift'] else None,
                    'end_time': self._minutes_to_time(day_data['shift']['end_minutes'] % (24 * 60)) if day_data['shift'] else None
                }
                rows.append(row)
        
        df = pd.DataFrame(rows)
        # 見やすいようにソート
        df = df.sort_values(['date', 'employee_name'])
        return df
    
    def export_to_csv(self, result, filename):
        """スケジュール結果をCSVファイルに出力"""
        df = self.get_shift_table(result)
        if df is not None:
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            return True
        return False
    
    def _minutes_to_time(self, minutes):
        """分単位の時間をHH:MM形式に変換"""
        h = minutes // 60
        m = minutes % 60
        return f"{h:02d}:{m:02d}"

# 使用例
if __name__ == "__main__":
    optimizer = ShiftOptimizer()
    
    # 従業員を追加
    optimizer.add_employee(1, "田中太郎", skills=["マネジメント", "レジ", "接客"], max_hours_week=40)
    optimizer.add_employee(2, "佐藤花子", skills=["接客", "レジ"], max_hours_week=30)
    optimizer.add_employee(3, "鈴木一郎", skills=["接客", "在庫管理"], max_hours_week=20)
    
    # シフトを追加
    optimizer.add_shift(1, "早番", "08:00", "16:00", required_skills=["レジ"], required_employees=1)
    optimizer.add_shift(2, "遅番", "16:00", "22:00", required_skills=["接客"], required_employees=2)
    
    # スケジュール期間を設定
    start_date = datetime.date(2023, 1, 1)
    end_date = datetime.date(2023, 1, 7)
    optimizer.set_schedule_period(start_date, end_date)
    
    # バッティング回避ペアを追加
    optimizer.add_avoidance_pair(1, 3)
    
    # 最適化実行
    result = optimizer.solve()
    
    if result['status'] == 'success':
        print("最適化成功")
        df = optimizer.get_shift_table(result)
        print(df)
        
        # CSVに出力
        optimizer.export_to_csv(result, "shift_schedule.csv")
    else:
        print(f"最適化失敗: {result['reason']}")