from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import pandas as pd
import numpy as np
import datetime
import os
import io
from shift_optimizer import ShiftOptimizer
from shift_request import ShiftRequestManager

app = Flask(__name__)
app.secret_key = 'shift_optimization_app'

# アプリケーションのグローバル変数
global_optimizer = None
global_result = None
global_request_manager = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/employees', methods=['GET', 'POST'])
def employees():
    global global_optimizer
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
    
    if request.method == 'POST':
        employee_id = int(request.form['employee_id'])
        name = request.form['name']
        skills = request.form.getlist('skills')
        max_hours_day = int(request.form['max_hours_day'])
        max_hours_week = int(request.form['max_hours_week'])
        max_consecutive_days = int(request.form['max_consecutive_days'])
        
        # 勤務不可日をリストに変換
        unavailable_days_str = request.form['unavailable_days']
        unavailable_days = []
        if unavailable_days_str.strip():
            for date_str in unavailable_days_str.split(','):
                try:
                    unavailable_days.append(datetime.datetime.strptime(date_str.strip(), '%Y-%m-%d').date())
                except ValueError:
                    flash(f'日付フォーマットエラー: {date_str}. YYYY-MM-DD形式で入力してください。')
        
        # 希望シフトをリストに変換
        preferred_shifts_str = request.form['preferred_shifts']
        preferred_shifts = []
        if preferred_shifts_str.strip():
            for shift_id in preferred_shifts_str.split(','):
                try:
                    preferred_shifts.append(int(shift_id.strip()))
                except ValueError:
                    flash(f'シフトIDエラー: {shift_id}. 数値を入力してください。')
        
        global_optimizer.add_employee(
            employee_id=employee_id,
            name=name,
            skills=skills,
            max_hours_day=max_hours_day,
            max_hours_week=max_hours_week,
            max_consecutive_days=max_consecutive_days,
            unavailable_days=unavailable_days,
            preferred_shifts=preferred_shifts
        )
        
        flash(f'従業員 {name} を追加しました。')
        return redirect(url_for('employees'))
    
    # 従業員一覧を表示
    employees_data = []
    if global_optimizer and global_optimizer.employees:
        for emp in global_optimizer.employees:
            employees_data.append({
                'id': emp['id'],
                'name': emp['name'],
                'skills': ', '.join(emp['skills']),
                'max_hours_day': emp['max_hours_day'],
                'max_hours_week': emp['max_hours_week'],
                'max_consecutive_days': emp['max_consecutive_days'],
                'unavailable_days': ', '.join(str(d) for d in emp['unavailable_days']),
                'preferred_shifts': ', '.join(str(s) for s in emp['preferred_shifts'])
            })
    
    return render_template('employees.html', employees=employees_data)

@app.route('/import_employees', methods=['POST'])
def import_employees():
    global global_optimizer
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
    
    if 'file' not in request.files:
        flash('ファイルがありません。')
        return redirect(url_for('employees'))
    
    file = request.files['file']
    if file.filename == '':
        flash('ファイルが選択されていません。')
        return redirect(url_for('employees'))
    
    if file and file.filename.endswith('.csv'):
        try:
            df = pd.read_csv(file, encoding='utf-8-sig')
            
            for _, row in df.iterrows():
                # 勤務不可日をリストに変換
                unavailable_days = []
                if pd.notna(row.get('unavailable_days', '')):
                    for date_str in str(row['unavailable_days']).split(','):
                        try:
                            unavailable_days.append(datetime.datetime.strptime(date_str.strip(), '%Y-%m-%d').date())
                        except ValueError:
                            pass
                
                # スキルをリストに変換
                skills = []
                if pd.notna(row.get('skills', '')):
                    skills = [s.strip() for s in str(row['skills']).split(',')]
                
                # 希望シフトをリストに変換
                preferred_shifts = []
                if pd.notna(row.get('preferred_shifts', '')):
                    for shift_id in str(row['preferred_shifts']).split(','):
                        try:
                            preferred_shifts.append(int(shift_id.strip()))
                        except ValueError:
                            pass
                
                global_optimizer.add_employee(
                    employee_id=int(row['employee_id']),
                    name=row['name'],
                    skills=skills,
                    max_hours_day=int(row.get('max_hours_day', 8)),
                    max_hours_week=int(row.get('max_hours_week', 40)),
                    max_consecutive_days=int(row.get('max_consecutive_days', 5)),
                    unavailable_days=unavailable_days,
                    preferred_shifts=preferred_shifts
                )
            
            flash(f'{len(df)} 人の従業員をインポートしました。')
        except Exception as e:
            flash(f'CSVインポートエラー: {str(e)}')
    else:
        flash('CSVファイルを選択してください。')
    
    return redirect(url_for('employees'))

@app.route('/shifts', methods=['GET', 'POST'])
def shifts():
    global global_optimizer
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
    
    if request.method == 'POST':
        shift_id = int(request.form['shift_id'])
        name = request.form['name']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        
        # スキル要件をリストに変換
        required_skills_str = request.form['required_skills']
        required_skills = []
        if required_skills_str.strip():
            required_skills = [s.strip() for s in required_skills_str.split(',')]
        
        required_employees = int(request.form['required_employees'])
        is_fixed = 'is_fixed' in request.form
        
        global_optimizer.add_shift(
            shift_id=shift_id,
            name=name,
            start_time=start_time,
            end_time=end_time,
            required_skills=required_skills,
            required_employees=required_employees,
            is_fixed=is_fixed
        )
        
        flash(f'シフト {name} を追加しました。')
        return redirect(url_for('shifts'))
    
    # シフト一覧を表示
    shifts_data = []
    if global_optimizer and global_optimizer.shifts:
        for shift in global_optimizer.shifts:
            start_time = global_optimizer._minutes_to_time(shift['start_minutes'])
            end_time = global_optimizer._minutes_to_time(shift['end_minutes'] % (24 * 60))
            
            shifts_data.append({
                'id': shift['id'],
                'name': shift['name'],
                'start_time': start_time,
                'end_time': end_time,
                'duration': f"{shift['duration'] // 60}時間{shift['duration'] % 60}分",
                'required_skills': ', '.join(shift['required_skills']),
                'required_employees': shift['required_employees'],
                'is_fixed': 'はい' if shift['is_fixed'] else 'いいえ'
            })
    
    return render_template('shifts.html', shifts=shifts_data)

@app.route('/import_shifts', methods=['POST'])
def import_shifts():
    global global_optimizer
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
    
    if 'file' not in request.files:
        flash('ファイルがありません。')
        return redirect(url_for('shifts'))
    
    file = request.files['file']
    if file.filename == '':
        flash('ファイルが選択されていません。')
        return redirect(url_for('shifts'))
    
    if file and file.filename.endswith('.csv'):
        try:
            df = pd.read_csv(file, encoding='utf-8-sig')
            
            for _, row in df.iterrows():
                # スキル要件をリストに変換
                required_skills = []
                if pd.notna(row.get('required_skills', '')):
                    required_skills = [s.strip() for s in str(row['required_skills']).split(',')]
                
                global_optimizer.add_shift(
                    shift_id=int(row['shift_id']),
                    name=row['name'],
                    start_time=row['start_time'],
                    end_time=row['end_time'],
                    required_skills=required_skills,
                    required_employees=int(row.get('required_employees', 1)),
                    is_fixed=str(row.get('is_fixed', '')).lower() in ['true', 'yes', 'はい', '1']
                )
            
            flash(f'{len(df)} 件のシフトをインポートしました。')
        except Exception as e:
            flash(f'CSVインポートエラー: {str(e)}')
    else:
        flash('CSVファイルを選択してください。')
    
    return redirect(url_for('shifts'))

@app.route('/shift_requests', methods=['GET', 'POST'])
def shift_requests():
    global global_optimizer
    global global_request_manager
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
    
    if global_request_manager is None:
        global_request_manager = ShiftRequestManager(global_optimizer)
    
    if request.method == 'POST':
        employee_id = int(request.form['employee_id'])
        date_str = request.form['date']
        
        try:
            date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # シフトタイプの処理
            shift_type = request.form['shift_type']
            
            if shift_type == 'day_off':
                # 休みの申請
                global_request_manager.add_request(
                    employee_id=employee_id,
                    date=date,
                    is_day_off=True
                )
                flash(f'従業員 ID: {employee_id} の {date_str} の休み希望を登録しました。')
                
            elif shift_type == 'shift_pattern':
                # シフトパターンの申請
                shift_name = request.form['shift_name']
                global_request_manager.add_request(
                    employee_id=employee_id,
                    date=date,
                    shift_name=shift_name
                )
                flash(f'従業員 ID: {employee_id} の {date_str} のシフト希望 "{shift_name}" を登録しました。')
                
            elif shift_type == 'time_specified':
                # 時刻指定の申請
                start_time = request.form['start_time']
                end_time = request.form['end_time']
                break_time = request.form.get('break_time', '')
                note = request.form.get('note', '')
                
                global_request_manager.add_request(
                    employee_id=employee_id,
                    date=date,
                    start_time=start_time,
                    end_time=end_time,
                    break_time=break_time,
                    note=note
                )
                flash(f'従業員 ID: {employee_id} の {date_str} の時刻指定シフト希望 ({start_time}-{end_time}) を登録しました。')
            
            return redirect(url_for('shift_requests'))
            
        except ValueError as e:
            flash(f'入力エラー: {str(e)}')
    
    # シフト希望一覧を表示
    requests_data = []
    if global_request_manager and global_request_manager.shift_requests:
        for req in global_request_manager.shift_requests:
            row = {
                'employee_id': req['employee_id'],
                'date': req['date'].strftime('%Y-%m-%d'),
                'is_day_off': '休み' if req['is_day_off'] else '',
                'shift_name': req['shift_name'] if req['shift_name'] else '',
                'time': ''
            }
            
            if req['start_minutes'] is not None and req['end_minutes'] is not None:
                start_time = global_optimizer._minutes_to_time(req['start_minutes'])
                end_time = global_optimizer._minutes_to_time(req['end_minutes'] % (24 * 60))
                row['time'] = f"{start_time} - {end_time}"
                
                if req['break_minutes']:
                    break_hours = req['break_minutes'] // 60
                    break_mins = req['break_minutes'] % 60
                    row['time'] += f" (休憩: {break_hours}時間{break_mins}分)"
            
            row['note'] = req['note'] if req['note'] else ''
            
            # 従業員名を取得
            for emp in global_optimizer.employees:
                if emp['id'] == req['employee_id']:
                    row['employee_name'] = emp['name']
                    break
            
            requests_data.append(row)
    
    # シフトパターン一覧を取得
    shift_patterns = []
    if global_optimizer and global_optimizer.shifts:
        for shift in global_optimizer.shifts:
            if not shift['name'].startswith('Request_'):  # 申請用の自動生成シフトは除外
                shift_patterns.append({
                    'id': shift['id'],
                    'name': shift['name']
                })
    
    # 従業員一覧を取得
    employees_data = []
    if global_optimizer and global_optimizer.employees:
        for emp in global_optimizer.employees:
            employees_data.append({
                'id': emp['id'],
                'name': emp['name']
            })
    
    return render_template('shift_requests.html', 
                          requests=requests_data, 
                          shift_patterns=shift_patterns,
                          employees=employees_data)

@app.route('/import_shift_requests', methods=['POST'])
def import_shift_requests():
    global global_optimizer
    global global_request_manager
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
    
    if global_request_manager is None:
        global_request_manager = ShiftRequestManager(global_optimizer)
    
    if 'file' not in request.files:
        flash('ファイルがありません。')
        return redirect(url_for('shift_requests'))
    
    file = request.files['file']
    if file.filename == '':
        flash('ファイルが選択されていません。')
        return redirect(url_for('shift_requests'))
    
    if file and file.filename.endswith('.csv'):
        try:
            # ファイルを読み込み
            file_content = io.StringIO(file.stream.read().decode('utf-8-sig'))
            
            # シフト希望をインポート
            count = global_request_manager.import_requests_from_csv(file_content=file_content)
            
            flash(f'{count} 件のシフト希望をインポートしました。')
        except Exception as e:
            flash(f'CSVインポートエラー: {str(e)}')
    else:
        flash('CSVファイルを選択してください。')
    
    return redirect(url_for('shift_requests'))

@app.route('/clear_shift_requests')
def clear_shift_requests():
    global global_request_manager
    
    if global_request_manager:
        global_request_manager.clear_requests()
        flash('すべてのシフト希望をクリアしました。')
    
    return redirect(url_for('shift_requests'))

@app.route('/apply_shift_requests')
def apply_shift_requests():
    global global_optimizer
    global global_request_manager
    
    if global_optimizer is None or global_request_manager is None:
        flash('従業員とシフトを先に登録してください。')
        return redirect(url_for('index'))
    
    try:
        count = global_request_manager.apply_requests_to_optimizer()
        flash(f'{count} 件のシフト希望を適用しました。スケジュール作成時に考慮されます。')
    except Exception as e:
        flash(f'シフト希望の適用エラー: {str(e)}')
    
    return redirect(url_for('schedule'))

@app.route('/schedule', methods=['GET', 'POST'])
def schedule():
    global global_optimizer
    global global_result
    
    if global_optimizer is None:
        global_optimizer = ShiftOptimizer()
        flash('従業員とシフトを先に登録してください。')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        start_date_str = request.form['start_date']
        end_date_str = request.form['end_date']
        
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            # スケジュール期間を設定
            global_optimizer.set_schedule_period(start_date, end_date)
            
            # バッティング回避ペアをリセット
            if hasattr(global_optimizer, 'avoidance_pairs'):
                global_optimizer.avoidance_pairs = []
            
            # バッティング回避ペアを追加
            avoidance_pairs_str = request.form['avoidance_pairs']
            if avoidance_pairs_str.strip():
                for pair_str in avoidance_pairs_str.split(','):
                    pair = pair_str.split('-')
                    if len(pair) == 2:
                        try:
                            emp1_id = int(pair[0].strip())
                            emp2_id = int(pair[1].strip())
                            global_optimizer.add_avoidance_pair(emp1_id, emp2_id)
                        except ValueError:
                            flash(f'バッティング回避ペアエラー: {pair_str}. "ID1-ID2"形式で入力してください。')
            
            # 最適化実行
            global_result = global_optimizer.solve()
            
            if global_result['status'] == 'success':
                # 制約違反の情報を表示
                violations = global_result.get('violations', {})
                
                if sum(violations.values()) > 0:
                    violation_msgs = []
                    if violations.get('required_employees_violations', 0) > 0:
                        violation_msgs.append(f"必要人数の不足: {int(violations['required_employees_violations'])}箇所")
                    if violations.get('unavailable_violations', 0) > 0:
                        violation_msgs.append(f"勤務不可日の出勤: {int(violations['unavailable_violations'])}箇所")
                    if violations.get('avoidance_violations', 0) > 0:
                        violation_msgs.append(f"バッティング回避の違反: {int(violations['avoidance_violations'])}箇所")
                    
                    if violation_msgs:
                        flash(f'スケジュールが作成されましたが、一部制約条件を緩和しました: {", ".join(violation_msgs)}')
                    else:
                        flash('スケジュール作成が完了しました！')
                else:
                    flash('全ての制約条件を満たしたスケジュールが作成されました！')
            else:
                debug_info = global_result.get('debug_info', {})
                status_name = debug_info.get('status_name', 'Unknown')
                flash(f'スケジュール作成に失敗しました: {status_name}')
                
                # 詳細情報も表示
                flash(f'詳細情報: 従業員数={debug_info.get("num_employees", "?")}、'
                      f'シフト数={debug_info.get("num_shifts", "?")}、'
                      f'期間={debug_info.get("num_days", "?")}日')
                
                # 対策案も表示
                flash('対策: 期間を短くする、従業員を増やす、シフトの必要人数を減らす、制約条件を緩めるなどを試してください。')
            
            return redirect(url_for('schedule'))
            
        except ValueError as e:
            flash(f'日付フォーマットエラー: {str(e)}. YYYY-MM-DD形式で入力してください。')
    
    # スケジュール結果を表示
    schedule_table = None
    if global_result and global_result['status'] == 'success':
        df = global_optimizer.get_shift_table(global_result)
        
        # ピボットテーブルに変換して見やすく表示
        pivot_df = df.pivot_table(
            index=['employee_name'],
            columns=['date'],
            values=['shift_name'],
            aggfunc=lambda x: ' '.join(str(v) for v in x)
        )
        
        # マルチインデックスを解除
        pivot_df.columns = [col[1] for col in pivot_df.columns]
        pivot_df = pivot_df.reset_index()
        
        # DataFrameをHTMLテーブルに変換
        schedule_table = pivot_df.to_html(classes='table table-striped table-bordered')
    
    return render_template('schedule.html', schedule_table=schedule_table)

@app.route('/export_schedule')
def export_schedule():
    global global_optimizer
    global global_result
    
    if global_result and global_result['status'] == 'success':
        df = global_optimizer.get_shift_table(global_result)
        
        # CSVファイルをメモリに書き込む
        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        
        # CSVファイルをダウンロード
        return send_file(
            output,
            as_attachment=True,
            download_name='shift_schedule.csv',
            mimetype='text/csv'
        )
    else:
        flash('エクスポートするスケジュールがありません。')
        return redirect(url_for('schedule'))

@app.route('/reset')
def reset():
    global global_optimizer
    global global_result
    global global_request_manager
    
    global_optimizer = ShiftOptimizer()
    global_result = None
    global_request_manager = ShiftRequestManager()
    
    flash('全てのデータをリセットしました。')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
