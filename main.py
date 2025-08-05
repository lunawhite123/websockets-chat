from fastapi import Depends, HTTPException, status, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import User
from database import engine, Base, get_db
from schemas import UserCreate, Token, UserResponse
from auth import hash_password, verify_password, create_token, get_current_user, decode_token

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.websockets: dict[WebSocket:str] = {}
    

    async def connect(self, websocket: WebSocket, username: str):
        await websocket.accept()
        self.websockets[websocket] = username
    
    async def disconnect(self, websocket: WebSocket):
        del self.websockets[websocket]

    @staticmethod
    async def send_personal_message(message: str, websocket: WebSocket):
        await websocket.send_text(message)
    
    async def broadcast(self, message: str):
        for socket in self.websockets.keys():
            try:
                await socket.send_text(message)

            except RuntimeError as e:
                print(f'Ошибка при отправке сообщения (возможно отключился) {e}')
                await self.websockets.disconnect(websocket)

            except Exception as e:
                print(f'Ошибка при отправке сообщения {e}')
                await self.websockets.disconnect(websocket)

manager = ConnectionManager()

@app.websocket('/ws')
async def websocket(websocket: WebSocket, db: AsyncSession = Depends(get_db)):
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

    
    await manager.connect(websocket, user.username)
    try:
        while True:
            message = await websocket.receive_text()
            completed_message = f'Пользователь {user.username}: {message}'
            await manager.broadcast(completed_message)

    except WebSocketDisconnect:
        await manager.disconnect(websocket=websocket)

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