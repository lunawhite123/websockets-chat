from fastapi import Depends, HTTPException, status, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import User, Message
from database import engine, Base, get_db
from schemas import UserCreate, Token, UserResponse
from auth import hash_password, verify_password, create_token, get_current_user, decode_token
import json

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.websockets: dict[str, dict[WebSocket, str]] = {}
        self.usernames_to_websockets: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, username: str, room: str):
        await websocket.accept()
        
        if not room in self.websockets:
            self.websockets[room] = {}
        
        self.websockets[room][websocket] = username
        self.usernames_to_websockets[username] = websocket
    
    async def disconnect(self, websocket: WebSocket, room: str):
        if room in self.websockets and websocket in self.websockets[room]:
            username = self.websockets[room].pop(websocket)
            
            if username in self.usernames_to_websockets:
                del self.usernames_to_websockets[username]
        
            if not self.websockets[room]:
                del self.websockets[room]
    
    async def send_private_message(self, message: str, recipient: str, sender: str, room: str):
        if not room in self.websockets:
            print('Указаная комната не существует')
            return (None, 'Указаная комната не существует')
        
        if not recipient in self.websockets[room].values() or not sender in self.websockets[room].values():
            print('Отправитель и получатель должны находится в одной комнате для отправки сообщений')
            return (None, 'Отправитель и получатель должны находится в одной комнате для отправки сообщений')

        websocket = self.usernames_to_websockets.get(recipient)
        if websocket:
            try:
                await websocket.send_text(message)
                
            except RuntimeError as e:
                print(f'Ошибка при отправке сообщения (возможно не в сети) {e}')
                await self.disconnect(websocket, room)
                return (None, 'Пользователь не в сети')

            except Exception as e:
                print(f'Ошибка при отправке сообщения {e}')
                await self.disconnect(websocket, room)
                return (None, 'Ошибка при отправке сообщения')
        else:
            print(f'Сообщение не отправлено, получатель {recipient} не найден или не в сети!')
            return (None, f'Сообщение не отправлено, получатель {recipient} не найден или не в сети!')
        return (True, "Сообщение успешно отправлено")
    
    async def broadcast(self, message: str, room: str):
        if not room in self.websockets:
            print('Указаная комната не существует')
            return (None, 'Указаная комната не существует')
        
        for socket in list(self.websockets[room].keys()):
            try:
                await socket.send_text(message)

            except RuntimeError as e:
                print(f'Ошибка при отправке сообщения (возможно отключился) {e}')
                await self.disconnect(socket, room)
                return (None, f'Ошибка при отправке сообщения (возможно отключился) {e}')

            except Exception as e:
                print(f'Ошибка при отправке сообщения {e}')
                await self.disconnect(socket, room)
                return (None, f'Ошибка при отправке сообщения (возможно отключился) {e}')
        return (True, "Сообщение успешно отправлено")

manager = ConnectionManager()

@app.websocket('/ws/{room}')
async def websocket(websocket: WebSocket, room: str, db: AsyncSession = Depends(get_db)):
    header = websocket.headers.get('Authorization')
    if not header or not header.lower().startswith('bearer '):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Authentication token required or malformed")
        return
    
    token_value = header.split(' ', 1)[1]
    
    try:
        user = await decode_token(token_value, db)
    except HTTPException as e:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=f"Authentication failed: {e.detail}"
        )
        print(f"WebSocket: Отклонено - ошибка аутентификации: {e.detail}")
        return 

    await manager.connect(websocket, user.username, room=room)
    
    try:
        while True:
            try:
                json_data = await websocket.receive_text()
                message = json.loads(json_data)
                completed_message = f'Пользователь {user.username}: {message['data']}'
                
                if message['type'] == 'broadcast':
                    success = await manager.broadcast(completed_message, room)
                    if not success[0]:
                        await websocket.send_text(json.dumps({'status': 'error', 'message': success[1]}))
                
                elif message['type'] == 'private':
                    success = await manager.send_private_message(completed_message, message['recipient'], user.username, room=room)
                    if not success[0]:
                        await websocket.send_text(json.dumps({'status': 'error', 'message': success[1]}))
                    
            
            except json.JSONDecodeError as e:
                print(f'Неверная информация в json {e}')
                await websocket.send_text(json.dumps({'status': 'error', 'message': f'Неверный JSON: {e}'}))
                continue 
            
            except KeyError as e:
                print(f'Отсутствует необходимая информация в json {e}')
                await websocket.send_text(json.dumps({'status': 'error', 'message': f'Отсутствует необходимая информация в json {e}'}))
                continue

    except WebSocketDisconnect as e:
        await manager.disconnect(websocket=websocket, room=room)
        print(f'Пользователь вышел {e}')
    
@app.on_event("startup")
async def startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.post('/register', response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def user_create(user_data: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    
    result = await db.execute(select(User).filter_by(username=user_data.username))
    result = result.scalar_one_or_none()
    if result:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Имя пользователя уже есть в системе')
    
    hashed_password = hash_password(user_data.password)
    user = User(username=user_data.username, hashed_password=hashed_password)

    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

@app.post('/token', response_model=Token)
async def get_token(form_data: OAuth2PasswordRequestForm = Depends() ,db: AsyncSession = Depends(get_db)) -> Token:
    
    user = await db.execute(select(User).filter_by(username=form_data.username))
    user = user.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    
    new_token = create_token(data={'username': user.username})
    token = Token(access_token=new_token)
    return token

@app.get('/users/me', response_model=UserResponse)
async def get_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user