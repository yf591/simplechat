# lambda/index.py
import json
import os
import boto3
import re  # 正規表現モジュールをインポート
from botocore.exceptions import ClientError
import urllib.request # これを追加した


# Lambda コンテキストからリージョンを抽出する関数
def extract_region_from_arn(arn):
    # ARN 形式: arn:aws:lambda:region:account-id:function:function-name
    match = re.search('arn:aws:lambda:([^:]+):', arn)
    if match:
        return match.group(1)
    return "us-east-1"  # デフォルト値

# # グローバル変数としてクライアントを初期化（初期値） ※Bedrockクライアントは不要なのでコメントアウト
# bedrock_client = None

# # モデルID
# MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-lite-v1:0")

# FastAPI API の URL を環境変数から取得するように変更
FASTAPI_API_URL = os.environ.get("FASTAPI_API_URL")

# 環境変数が設定されているか確認 (デプロイエラーを防ぐために念のため追加した)
if not FASTAPI_API_URL:
    # 本来はここでエラーにするべきだと思いますが、Lambda実行時のエラーとするためここではprintのみ
    print("WARN: FASTAPI_API_URL environment variable is not set!")

def lambda_handler(event, context):
    try:
        # # コンテキストから実行リージョンを取得し、クライアントを初期化
        # global bedrock_client
        # if bedrock_client is None:
        #     region = extract_region_from_arn(context.invoked_function_arn)
        #     bedrock_client = boto3.client('bedrock-runtime', region_name=region)
        #     print(f"Initialized Bedrock client in region: {region}")
        
        # print("Received event:", json.dumps(event))

        print("Received event:", json.dumps(event))
        
        # Cognitoで認証されたユーザー情報を取得
        user_info = None
        if 'requestContext' in event and 'authorizer' in event['requestContext']:
            user_info = event['requestContext']['authorizer']['claims']
            print(f"Authenticated user: {user_info.get('email') or user_info.get('cognito:username')}")
        
        # リクエストボディの解析
        body = json.loads(event['body'])
        message = body['message']
        conversation_history = body.get('conversationHistory', [])
        
        print("Processing message:", message)
        # print("Using model:", MODEL_ID) # モデルIDは不要なのでコメントアウトした

        print("Calling FastAPI API at:", FASTAPI_API_URL) # FastAPI呼び出しを示すログを追加した
        

        ### Bedrock API 呼び出しの部分を FastAPI API 呼び出しに置き換えた（ここから） ###

        # 会話履歴を使用
        messages = conversation_history.copy()

        # ユーザーメッセージを追加
        messages.append({
            "role": "user",
            "content": message
        })

        # FastAPI API に送るペイロードを構築
        # 最初はシンプルにユーザーメッセージをpromptとして送る
        fastapi_payload = {
            "prompt": message,
            # FastAPIのapp.pyにある SimpleGenerationRequest に合うように他のパラメータも追加した
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
            "do_sample": True
        }
        
        # # invoke_model用のリクエストペイロード
        # request_payload = {
        #     "messages": bedrock_messages,
        #     "inferenceConfig": {
        #         "maxTokens": 512,
        #         "stopSequences": [],
        #         "temperature": 0.7,
        #         "topP": 0.9
        #     }
        # }
        
        # ペイロードをJSON文字列に変換してバイト列にエンコード
        data = json.dumps(fastapi_payload).encode('utf-8')

        # リクエストオブジェクトの作成
        # FASTAPI_API_URL が設定されているかここでチェックする
        if not FASTAPI_API_URL:
            raise ValueError("FASTAPI_API_URL environment variable is not set!")

        req = urllib.request.Request(
            url=f"{FASTAPI_API_URL}/generate", # FastAPIの /generate エンドポイントを指定
            data=data,
            headers={'Content-Type': 'application/json'}, # JSON形式で送信するように指定
            method='POST' # POSTメソッドを指定
        )

        print(f"Sending POST request to {req.full_url} with payload size {len(data)} bytes")

        # リクエストを送信し、レスポンスを取得
        # HTTPエラーなどもここで捕捉されるようにする
        try:
            with urllib.request.urlopen(req, timeout=20) as res: # timeoutを付けてLambdaのタイムアウトより早く失敗させられるようにした
                # レスポンスボディをバイト列として取得
                response_body_bytes = res.read()
                # レスポンスボディをJSONとして解析
                fastapi_response_body = json.loads(response_body_bytes.decode('utf-8'))

            print("FastAPI response received.")

            # FastAPI レスポンスの解析
            # FastAPIの /generate エンドポイントを'generated_text'というキーで応答を返すことを想定した
            assistant_response = fastapi_response_body.get('generated_text')

            if not assistant_response:
                # 'generated_text'がレスポンスに含まれていない場合はエラーにする
                print("Error: 'generated_text' not found in FastAPI response.")
                # デバッグのためレスポンス全体をエラーメッセージとして含めることにした
                raise Exception(f"Invalid FastAPI response format: {json.dumps(fastapi_response_body)}")

        except urllib.error.HTTPError as e:
            # HTTPエラー（400番台、500番台など）が発生した場合を想定
            error_body = e.read().decode('utf-8')
            print(f"HTTP Error: {e.code} - {error_body}")
            raise Exception(f"FastAPI HTTP Error: {e.code} - {error_body}")
        except urllib.error.URLError as e:
            # URLへの接続自体に問題がある場合（タイムアウト、名前解決など）を想定
            print(f"URL Error: {e.reason}")
            raise Exception(f"FastAPI URL Error: {e.reason}")
        except Exception as e:
            # その他のエラー（JSON解析エラーなど）の場合を想定
            print(f"Request Error: {e}")
            raise Exception(f"FastAPI Request Failed: {e}")
        
        ### Bedrock API 呼び出しの部分を FastAPI API 呼び出しに置き換えた（ここまで） ###



        # アシスタントの応答を会話履歴に追加
        messages.append({
            "role": "assistant",
            "content": assistant_response
        })
        
        # 成功レスポンスの返却
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": True,
                "response": assistant_response, # FastAPIの応答を返す
                "conversationHistory": messages # 更新された会話履歴を返す
            })
        }
        
    except Exception as error:
        print("Error:", str(error))
        
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False, 
                "error": str(error) # エラーメッセージを返す
            })
        }
