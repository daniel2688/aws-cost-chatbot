import boto3
import json
import uuid
from datetime import datetime
import os

# 🔹 Clientes AWS
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
bedrock_agent_admin   = boto3.client('bedrock-agent', region_name='us-east-1')
dynamodb              = boto3.resource('dynamodb')

AGENT_ID      = os.environ["AGENT_ID"]
AGENT_ALIAS   = os.environ["AGENT_ALIAS"]
HISTORY_TABLE = os.environ["HISTORY_TABLE"]

CORS_HEADERS = {
    'Access-Control-Allow-Origin' : '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'POST,OPTIONS'
}

def get_or_create_session(pk):
    table = dynamodb.Table(HISTORY_TABLE)
    try:
        resp = table.get_item(Key={'session_id': pk})
        item = resp.get('Item', {})
        return item.get('bedrock_session', str(uuid.uuid4()))
    except Exception as e:
        print("Error get_or_create_session:", str(e))
        return str(uuid.uuid4())

def save_session(pk, bedrock_session, user_email, messages):
    table = dynamodb.Table(HISTORY_TABLE)
    table.put_item(Item={
        'session_id'     : pk,
        'bedrock_session': bedrock_session,
        'user'           : user_email,
        'messages'       : messages[-200:],
        'updated_at'     : datetime.utcnow().isoformat()
    })

def load_messages(pk):
    table = dynamodb.Table(HISTORY_TABLE)
    try:
        resp = table.get_item(Key={'session_id': pk})
        item = resp.get('Item', {})
        return item.get('messages', [])
    except Exception as e:
        print("Error load_messages:", str(e))
        return []

def resumen_historial(messages):
    total    = len(messages)
    usuarios = [m for m in messages if m['role'] == 'user']
    if total == 0:
        return ''
    primera_fecha = messages[0].get('ts', '')[:10]
    return (
        f"📂 Tienes {len(usuarios)} consulta{'s' if len(usuarios) != 1 else ''} previas "
        f"desde {primera_fecha}. Continúa donde lo dejaste."
    )

def debug_agent():
    try:
        aliases = bedrock_agent_admin.list_agent_aliases(agentId=AGENT_ID)
        print("Aliases disponibles:", json.dumps(aliases, indent=2, default=str))
    except Exception as e:
        print("Error listando aliases:", str(e))

def lambda_handler(event, context):
    print("=== DEBUG START ===")
    print("Agent ID:", AGENT_ID)
    print("Alias ID:", AGENT_ALIAS)
    print("Incoming event:", json.dumps(event))

    user_email = "unknown"
    try:
        claims     = event['requestContext']['authorizer']['jwt']['claims']
        user_email = claims.get("email", "unknown")
        print("Usuario autenticado:", user_email)
    except Exception as e:
        print("⚠️ No se pudo leer claims:", str(e))

    debug_agent()

    if event.get('httpMethod') == 'OPTIONS':
        return {'statusCode': 200, 'headers': CORS_HEADERS, 'body': ''}

    try:
        body = json.loads(event.get('body') or '{}')
    except json.JSONDecodeError:
        body = {}

    user_msg = body.get('message', '').strip()
    action   = body.get('action', 'chat')

    session_id_frontend = body.get('session_id', 'default')
    session_id          = f"{user_email}#{session_id_frontend}"
    pk_historial        = f"user#{user_email}"

    if action == 'get_history':
        messages = load_messages(pk_historial)
        return {
            'statusCode': 200,
            'headers'   : CORS_HEADERS,
            'body'      : json.dumps({
                'messages': messages,
                'summary' : resumen_historial(messages),
                'total'   : len(messages)
            })
        }

    if action == 'clear_history':
        table = dynamodb.Table(HISTORY_TABLE)
        try:
            table.put_item(Item={
                'session_id'     : pk_historial,
                'bedrock_session': str(uuid.uuid4()),
                'user'           : user_email,
                'messages'       : [],
                'updated_at'     : datetime.utcnow().isoformat()
            })
        except Exception as e:
            print("Error clear_history:", str(e))
        return {
            'statusCode': 200,
            'headers'   : CORS_HEADERS,
            'body'      : json.dumps({'cleared': True, 'message': 'Historial borrado correctamente.'})
        }

    if not user_msg:
        return {
            'statusCode': 400,
            'headers'   : CORS_HEADERS,
            'body'      : json.dumps({'error': 'mensaje vacío'})
        }

    bedrock_session = get_or_create_session(session_id)
    messages = load_messages(pk_historial)

    try:
        response = bedrock_agent_runtime.invoke_agent(
            agentId      = AGENT_ID,
            agentAliasId = AGENT_ALIAS,
            sessionId    = bedrock_session,
            inputText    = user_msg
        )

        respuesta  = ""
        completion = response.get('completion') or []
        for event_chunk in completion:
            if 'chunk' in event_chunk:
                respuesta += event_chunk['chunk']['bytes'].decode('utf-8')

        save_session(session_id, bedrock_session, user_email, [])

        now = datetime.utcnow().isoformat()
        messages.append({'role': 'user',      'content': user_msg,  'ts': now})
        messages.append({'role': 'assistant', 'content': respuesta, 'ts': now})
        save_session(pk_historial, bedrock_session, user_email, messages)

        return {
            'statusCode': 200,
            'headers'   : {**CORS_HEADERS, 'Content-Type': 'application/json'},
            'body'      : json.dumps({
                'response'     : respuesta,
                'session_id'   : session_id,
                'user'         : user_email,
                'history_count': len(messages)
            })
        }

    except Exception as e:
        print("❌ ERROR INVOKE:", str(e))
        return {
            'statusCode': 500,
            'headers'   : CORS_HEADERS,
            'body'      : json.dumps({
                'error'   : str(e),
                'agent_id': AGENT_ID,
                'alias_id': AGENT_ALIAS
            })
        }
