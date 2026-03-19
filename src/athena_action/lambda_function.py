import boto3
import json
import os
import time
from datetime import datetime, timedelta
from collections import defaultdict

athena = boto3.client('athena')
orgs   = boto3.client('organizations')

DATABASE = os.environ.get("ATHENA_DATABASE", "aws_costs")
TABLE    = os.environ.get("ATHENA_TABLE",    "data")
OUTPUT   = os.environ.get("ATHENA_OUTPUT",   "s3://athena-cost-by-account-results/athena-results/")

CUR_START_DATE = "2026-03-01"


def get_account_names():
    account_map = {}
    try:
        paginator = orgs.get_paginator('list_accounts')
        for page in paginator.paginate():
            for a in page['Accounts']:
                account_map[a['Id']] = a['Name']
    except Exception as e:
        print(f"⚠️ No se pudieron obtener nombres de cuentas: {e}")
    return account_map


def run_athena_query(sql):
    resp = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={'Database': DATABASE},
        ResultConfiguration={'OutputLocation': OUTPUT},
        WorkGroup='primary'
    )
    qid = resp['QueryExecutionId']

    while True:
        r     = athena.get_query_execution(QueryExecutionId=qid)
        state = r['QueryExecution']['Status']['State']
        if state == 'SUCCEEDED':
            break
        if state in ['FAILED', 'CANCELLED']:
            raise Exception(f"Athena failed: {r['QueryExecution']['Status'].get('StateChangeReason')}")
        time.sleep(2)

    rows, nxt = [], None
    while True:
        args = {'QueryExecutionId': qid}
        if nxt:
            args['NextToken'] = nxt
        res = athena.get_query_results(**args)
        rows.extend(res['ResultSet']['Rows'])
        nxt = res.get('NextToken')
        if not nxt:
            break

    return rows[1:]


def get_costs_by_period(days=30, start_date=None, end_date=None):
    today = datetime.utcnow()

    if start_date and end_date:
        pass
    else:
        end_date   = today.strftime('%Y-%m-%d')
        start_date = (today - timedelta(days=days)).strftime('%Y-%m-%d')

    if start_date < CUR_START_DATE:
        print(f"⚠️ start_date {start_date} ajustado al mínimo {CUR_START_DATE}")
        start_date = CUR_START_DATE

    print(f"📅 Consultando período: {start_date} → {end_date}")

    account_names = get_account_names()

    sql = f"""
    SELECT
        line_item_usage_account_id,
        line_item_product_code,
        SUM(line_item_unblended_cost) AS total_cost
    FROM {TABLE}
    WHERE line_item_line_item_type = 'Usage'
      AND date(line_item_usage_start_date)
          BETWEEN DATE('{start_date}') AND DATE('{end_date}')
    GROUP BY line_item_usage_account_id, line_item_product_code
    ORDER BY total_cost DESC
    """
    rows = run_athena_query(sql)

    by_account = defaultdict(list)
    for row in rows:
        acct    = row['Data'][0].get('VarCharValue', 'N/A')
        service = row['Data'][1].get('VarCharValue', 'N/A')
        cost    = float(row['Data'][2].get('VarCharValue', '0') or 0)
        if cost >= 0.01:
            by_account[acct].append((service, cost))

    result = []
    for acct_id, services in by_account.items():
        name  = account_names.get(acct_id, acct_id)
        total = sum(c for _, c in services)
        result.append({
            "account_id"  : acct_id,
            "account_name": name,
            "total_cost"  : round(total, 2),
            "top_services": [
                {"service": s, "cost": round(c, 2)}
                for s, c in sorted(services, key=lambda x: x[1], reverse=True)[:5]
            ]
        })

    return {
        "period"  : f"{start_date} al {end_date}",
        "accounts": sorted(result, key=lambda x: x['total_cost'], reverse=True)
    }


def get_cost_alerts(days=7, threshold=500):
    today      = datetime.utcnow()
    end_date   = today.strftime('%Y-%m-%d')

    start_curr = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    if start_curr < CUR_START_DATE:
        start_curr = CUR_START_DATE

    start_prev = (today - timedelta(days=days*2)).strftime('%Y-%m-%d')
    end_prev   = (today - timedelta(days=days+1)).strftime('%Y-%m-%d')
    if start_prev < CUR_START_DATE:
        start_prev = CUR_START_DATE
    if end_prev   < CUR_START_DATE:
        end_prev   = CUR_START_DATE

    account_names = get_account_names()

    sql = f"""
    SELECT
        line_item_usage_account_id,
        line_item_product_code,
        SUM(CASE
            WHEN date(line_item_usage_start_date)
                 BETWEEN DATE('{start_curr}') AND DATE('{end_date}')
            THEN line_item_unblended_cost ELSE 0
        END) AS cost_current,
        SUM(CASE
            WHEN date(line_item_usage_start_date)
                 BETWEEN DATE('{start_prev}') AND DATE('{end_prev}')
            THEN line_item_unblended_cost ELSE 0
        END) AS cost_previous
    FROM {TABLE}
    WHERE line_item_line_item_type = 'Usage'
      AND date(line_item_usage_start_date)
          BETWEEN DATE('{start_prev}') AND DATE('{end_date}')
    GROUP BY line_item_usage_account_id, line_item_product_code
    ORDER BY cost_current DESC
    """
    rows = run_athena_query(sql)

    by_account_curr = defaultdict(list)
    by_account_prev = defaultdict(float)

    for row in rows:
        acct     = row['Data'][0].get('VarCharValue', 'N/A')
        service  = row['Data'][1].get('VarCharValue', 'N/A')
        cost_cur = float(row['Data'][2].get('VarCharValue', '0') or 0)
        cost_pre = float(row['Data'][3].get('VarCharValue', '0') or 0)

        if service.startswith('1k8isd'):
            service = 'Pinecone (AWS Marketplace)'
        elif service.startswith('17khu') or service.startswith('9svps'):
            service = 'Claude Bedrock Model'

        if cost_cur >= 0.01:
            by_account_curr[acct].append({'service': service, 'cost': round(cost_cur, 2)})
        by_account_prev[acct] += cost_pre

    alerts_spike      = []
    alerts_threshold  = []

    for acct_id, services in by_account_curr.items():
        name         = account_names.get(acct_id, acct_id)
        total_curr   = sum(s['cost'] for s in services)
        total_prev   = round(by_account_prev[acct_id], 2)
        increment    = round(total_curr - total_prev, 2)
        top_services = sorted(services, key=lambda x: x['cost'], reverse=True)[:5]

        if total_curr >= threshold:
            alerts_threshold.append({
                "type"        : "threshold",
                "account_id"  : acct_id,
                "account_name": name,
                "period"      : f"{start_curr} → {end_date}",
                "total_cost"  : total_curr,
                "threshold"   : threshold,
                "top_services": top_services,
                "message"     : f"La cuenta {name} acumuló ${total_curr:.2f} USD en el período {start_curr}→{end_date}, superando el umbral de ${threshold} USD."
            })

        if increment >= threshold and total_prev > 0:
            alerts_spike.append({
                "type"          : "spike",
                "account_id"    : acct_id,
                "account_name"  : name,
                "period_current": f"{start_curr} → {end_date}",
                "period_prev"   : f"{start_prev} → {end_prev}",
                "cost_current"  : total_curr,
                "cost_previous" : total_prev,
                "increment"     : increment,
                "top_services"  : top_services,
                "message"       : f"La cuenta {name} subió ${increment:.2f} USD vs el período anterior (de ${total_prev:.2f} a ${total_curr:.2f} USD)."
            })

    total_alertas = len(alerts_threshold) + len(alerts_spike)

    return {
        "period_current" : f"{start_curr} → {end_date}",
        "period_previous": f"{start_prev} → {end_prev}",
        "threshold"      : threshold,
        "days_analyzed"  : days,
        "total_alerts"   : total_alertas,
        "alerts_threshold": alerts_threshold,
        "alerts_spike"   : alerts_spike,
        "summary"        : f"Se encontraron {total_alertas} alertas: "
                           f"{len(alerts_threshold)} cuentas superaron ${threshold} USD "
                           f"y {len(alerts_spike)} tuvieron un incremento > ${threshold} USD."
    }


def lambda_handler(event, context):
    print(f"📥 Event recibido: {json.dumps(event)}")

    action = event.get('actionGroup', '')
    func   = event.get('function', '')
    params = event.get('parameters', [])

    param_dict = {p['name']: p['value'] for p in params}

    days       = int(param_dict.get('days', 7))
    threshold  = float(param_dict.get('threshold', 500))
    start_date = param_dict.get('start_date', None)
    end_date   = param_dict.get('end_date',   None)

    try:
        if func == 'get_costs_by_period':
            data = get_costs_by_period(days=days, start_date=start_date, end_date=end_date)
            response_body = json.dumps(data, ensure_ascii=False)
        elif func == 'get_cost_alerts':
            data = get_cost_alerts(days=days, threshold=threshold)
            response_body = json.dumps(data, ensure_ascii=False)
        else:
            response_body = json.dumps({"error": f"Función '{func}' no reconocida"})

    except Exception as e:
        print(f"❌ Error: {e}")
        response_body = json.dumps({"error": str(e)})

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action,
            "function"   : func,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": response_body
                    }
                }
            }
        }
    }
