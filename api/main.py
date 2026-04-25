"""
VibeShare Backend — FastAPI
Modern REST API with Clerk JWT authentication, SQLAlchemy ORM, and Cloudinary image uploads.
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
from random import shuffle
import cloudinary
from cloudinary.uploader import upload as cloudinary_upload
import jwt
import httpx
import os
from dotenv import load_dotenv
from functools import lru_cache
import re
from collections import Counter

load_dotenv()

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    api_key=os.getenv("CLOUDINARY_API_KEY", ""),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", ""),
)

# ──────────────────────────────────────────────
# Database Setup
# ──────────────────────────────────────────────

# Fix for Windows users missing psycopg2 C compilers: 
# Dynamically switch the postgres connection to use the pure python pg8000 driver.
import ssl

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+pg8000://", 1)
    # pg8000 doesn't accept libpq's sslmode parameter, so strip query params
    if "?" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.split("?")[0]
        
    engine = create_engine(DATABASE_URL, connect_args={"ssl_context": ssl.create_default_context()}) if DATABASE_URL else None
else:
    engine = create_engine(DATABASE_URL) if DATABASE_URL else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
Base = declarative_base()


def get_db():
    """Dependency that provides a database session per request."""
    if not SessionLocal:
        raise HTTPException(status_code=500, detail="Database not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────────────────────────────
# SQLAlchemy Models
# ──────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    clerk_id = Column(String(200), unique=True, index=True, nullable=True)
    name = Column(String(100), nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    img = Column(String(1000), default="")
    bio = Column(String(300), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    posts = relationship("Post", back_populates="author", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    likes = relationship("Like", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username}>"


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(100), ForeignKey("users.email"), nullable=False)
    username = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    text = Column(String(500), default="")
    img = Column(String(1000), default="")
    pfp = Column(String(1000), default="")

    author = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    post_likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Post {self.id}>"


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_email = Column(String(100), ForeignKey("users.email"), nullable=False)

    post = relationship("Post", back_populates="post_likes")
    user = relationship("User", back_populates="likes")

    def __repr__(self):
        return f"<Like {self.id}>"


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String(100), ForeignKey("users.email"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    text = Column(String(300), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    name = Column(String(100), default="")

    user = relationship("User", back_populates="comments")
    post = relationship("Post", back_populates="comments")

    def __repr__(self):
        return f"<Comment {self.id}>"


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_email = Column(String(100), ForeignKey("users.email"), nullable=False)
    following_email = Column(String(100), ForeignKey("users.email"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Follow {self.follower_email} -> {self.following_email}>"


# ──────────────────────────────────────────────
# Pydantic Schemas
# ──────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str = Field(..., max_length=100)
    username: str = Field(..., max_length=100)
    email: str = Field(..., max_length=100)
    pfp: Optional[str] = ""
    clerk_id: Optional[str] = ""

class PostCreate(BaseModel):
    user_email: str
    text: Optional[str] = ""
    img: Optional[str] = ""
    width: Optional[int] = None
    height: Optional[int] = None
    crop: Optional[str] = None

class UpdateUserRequest(BaseModel):
    email: str
    new_username: str = Field(..., max_length=100)

class LikeRequest(BaseModel):
    post_id: int
    user_email: str

class CheckLikedRequest(BaseModel):
    post_id: int
    user_email: str

class CommentCreate(BaseModel):
    post_id: int
    user_email: str
    text: str = Field(..., max_length=300)
    name: Optional[str] = ""

class GetCommentsRequest(BaseModel):
    post_id: int

class GetUserRequest(BaseModel):
    username: str

class GetUserByEmailRequest(BaseModel):
    email: str

class GetPostRequest(BaseModel):
    post_id: int

class DeletePostRequest(BaseModel):
    post_id: int
    user_email: str

class FollowRequest(BaseModel):
    follower_email: str
    following_email: str

class SearchRequest(BaseModel):
    query: str = Field(..., max_length=100)

# Response schemas
class UserResponse(BaseModel):
    name: str
    username: str
    pfp: str
    email: Optional[str] = None
    bio: Optional[str] = ""

class PostResponse(BaseModel):
    post_id: int
    name: str
    username: str
    text: str
    pfp: str
    img: str
    likes: int

class CommentResponse(BaseModel):
    name: str
    email: str
    text: str


# ──────────────────────────────────────────────
# Clerk JWT Authentication
# ──────────────────────────────────────────────

_jwks_cache = None

async def get_clerk_jwks():
    """Fetch and cache Clerk's JWKS public keys for JWT verification."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    if not CLERK_JWKS_URL:
        return None

    async with httpx.AsyncClient() as client:
        response = await client.get(CLERK_JWKS_URL)
        _jwks_cache = response.json()
        return _jwks_cache


async def verify_clerk_token(authorization: Optional[str] = Header(None)):
    """
    FastAPI dependency that verifies the Clerk JWT Bearer token.
    Returns the decoded payload with user claims, or None if no token provided.
    Protected routes should check if the return value is None.
    """
    if not authorization:
        return None

    try:
        token = authorization.replace("Bearer ", "")
        jwks_data = await get_clerk_jwks()

        if not jwks_data:
            # If JWKS not configured, skip verification (development mode)
            return {"sub": "dev-user"}

        # Get the signing key from JWKS
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        rsa_key = None
        for key in jwks_data.get("keys", []):
            if key["kid"] == kid:
                rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                break

        if not rsa_key:
            raise HTTPException(status_code=401, detail="Invalid token signing key")

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        return None


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────

app = FastAPI(
    title="VibeShare API",
    description="Social media platform API with Clerk authentication",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def create_tables():
    """Create all database tables on startup."""
    if engine:
        Base.metadata.create_all(bind=engine)


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────

def upload_image(base64_image: str, width: Optional[int] = None, height: Optional[int] = None, crop: str = "fill") -> dict:
    """Upload a base64 image to Cloudinary with optional resizing/cropping."""
    try:
        transformations = {}
        if width or height:
            transformations["width"] = width
            transformations["height"] = height
            transformations["crop"] = crop
            transformations["gravity"] = "center"
        
        options = {}
        if transformations:
            options["transformation"] = [transformations]
        
        result = cloudinary_upload(base64_image, **options)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")


def get_likes_count(db: Session, post_id: int) -> int:
    """Get the total number of likes for a post."""
    return db.query(Like).filter(Like.post_id == post_id).count()


def get_comments_count(db: Session, post_id: int) -> int:
    """Get the total number of comments for a post."""
    return db.query(Comment).filter(Comment.post_id == post_id).count()


# ──────────────────────────────────────────────
# Routes — Health Check
# ──────────────────────────────────────────────

@app.get("/")
async def root():
    """Root health check endpoint."""
    return {"status": True, "message": "VibeShare API v2.0"}


@app.get("/api/get-trending-tags")
async def get_trending_tags(db: Session = Depends(get_db)):
    posts = db.query(Post).all()
    comments = db.query(Comment).all()
    all_text = " ".join([p.text or "" for p in posts] + [c.text or "" for c in comments])
    
    tags = re.findall(r"#(\w+)", all_text.lower())
    
    # Count frequencies
    counts = Counter(tags).most_common(6)
    
    trending = [
        {"tag": f"#{tag}", "count": count}
        for tag, count in counts
    ]
    
    return {"status": True, "trending": trending}


@app.get("/api/home")
async def home():
    """API health check endpoint."""
    return {"status": True, "message": "API is running"}


# ──────────────────────────────────────────────
# Routes — Users
# ──────────────────────────────────────────────

@app.post("/api/create-user")
async def create_user(data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user. Skips if email already exists."""
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        return {"status": True, "message": "User already exists"}

    new_user = User(
        email=data.email,
        name=data.name,
        username=data.username,
        img=data.pfp or "",
        clerk_id=data.clerk_id or "",
    )
    db.add(new_user)
    db.commit()
    return {"status": True, "message": "User created successfully"}


@app.post("/api/get-user")
async def get_user(
    data: GetUserRequest,
    db: Session = Depends(get_db), 
):
    """Get user profile by username."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    followers = db.query(Follow).filter(Follow.following_email == user.email).count()
    following = db.query(Follow).filter(Follow.follower_email == user.email).count()

    return {
        "status": True,
        "user": {
            "name": user.name,
            "username": user.username,
            "pfp": user.img,
            "email": user.email,
            "bio": user.bio or "",
            "followers": followers,
            "following": following,
        }
    }

@app.post("/api/get-user-by-email")
async def get_user_by_email(
    data: GetUserByEmailRequest,
    db: Session = Depends(get_db), 
):
    """Get user profile by email."""
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    followers = db.query(Follow).filter(Follow.following_email == user.email).count()
    following = db.query(Follow).filter(Follow.follower_email == user.email).count()

    return {
        "status": True,
        "user": {
            "name": user.name,
            "username": user.username,
            "pfp": user.img,
            "email": user.email,
            "bio": user.bio or "",
            "followers": followers,
            "following": following,
        }
    }


@app.get("/api/get-featured")
async def get_featured(db: Session = Depends(get_db)):
    """Get up to 6 random featured users."""
    users = db.query(User).limit(20).all()
    featured = [
        {"name": u.name, "username": u.username, "img": u.img, "email": u.email}
        for u in users
    ]
    shuffle(featured)
    return {
        "status": True,
        "message": "Fetched users",
        "accounts": featured[:6],
    }


@app.post("/api/search-users")
async def search_users(data: SearchRequest, db: Session = Depends(get_db)):
    """Search users by username or name."""
    query = f"%{data.query}%"
    users = (
        db.query(User)
        .filter(
            (User.username.ilike(query)) | (User.name.ilike(query))
        )
        .limit(20)
        .all()
    )
    results = [
        {"name": u.name, "username": u.username, "img": u.img, "bio": u.bio or "", "email": u.email}
        for u in users
    ]
    return {"status": True, "results": results}


# ──────────────────────────────────────────────
# Routes — Posts
# ──────────────────────────────────────────────

@app.get("/api/get-posts")
async def get_posts(db: Session = Depends(get_db)):
    """Get all posts with like counts."""
    posts = db.query(Post).order_by(Post.created_at.desc()).all()
    all_posts = []
    for post in posts:
        author = db.query(User).filter(User.email == post.user_email).first()
        all_posts.append({
            "post_id": post.id,
            "name": author.name if author else post.username,
            "username": post.username,
            "user_email": post.user_email,
            "text": post.text,
            "pfp": author.img if author else post.pfp,
            "img": post.img,
            "likes": get_likes_count(db, post.id),
            "comment_count": get_comments_count(db, post.id),
            "created_at": post.created_at.isoformat() if post.created_at else "",
        })
    return {"posts": all_posts, "status": True}


@app.post("/api/get-post")
async def get_post(data: GetPostRequest, db: Session = Depends(get_db)):
    """Get a single post by ID."""
    post = db.query(Post).filter(Post.id == data.post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    author = db.query(User).filter(User.email == post.user_email).first()
    return {
        "status": True,
        "name": author.name if author else post.username,
        "username": post.username,
        "user_email": post.user_email,
        "pfp": author.img if author else post.pfp,
        "img": post.img,
        "text": post.text,
        "post_id": post.id,
        "likes": get_likes_count(db, post.id),
        "comment_count": get_comments_count(db, post.id),
        "created_at": post.created_at.isoformat() if post.created_at else "",
    }


@app.post("/api/create-post")
async def create_post(
    data: PostCreate,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Create a new post. Requires authentication."""
    img_url = ""
    if data.img:
        try:
            image_data = upload_image(
                data.img, 
                width=data.width, 
                height=data.height, 
                crop=data.crop or "fill"
            )
            img_url = image_data.get("secure_url", "")
        except Exception as e:
            print(f"Cloudinary upload error: {e}")
            raise HTTPException(status_code=500, detail="Image upload failed")

    # Look up correct user info from database
    user = db.query(User).filter(User.email == data.user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_post = Post(
        user_email=user.email,
        username=user.username,
        created_at=datetime.utcnow(),
        text=data.text or "",
        img=img_url,
        pfp=user.img or "",
    )
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    return {"status": True, "post_id": new_post.id}


@app.post("/api/delete-post")
async def delete_post(
    data: DeletePostRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Delete a post. Only the post owner can delete."""
    post = db.query(Post).filter(Post.id == data.post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if post.user_email != data.user_email:
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")

    db.delete(post)
    db.commit()
    return {"status": True, "message": "Post deleted successfully"}


@app.post("/api/update-user")
async def update_user(
    data: UpdateUserRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Update a user's username."""
    # Check if username is already taken
    existing = db.query(User).filter(User.username == data.new_username).first()
    if existing and existing.email != data.email:
        raise HTTPException(status_code=400, detail="Username already taken")
        
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    old_username = user.username
    user.username = data.new_username
    
    # Also update username in their posts
    posts = db.query(Post).filter(Post.user_email == data.email).all()
    for p in posts:
        p.username = data.new_username
        
    db.commit()
    return {"status": True, "message": "Username updated"}


@app.post("/api/get-user-posts")
async def get_user_posts(data: GetUserRequest, db: Session = Depends(get_db)):
    """Get all posts by a specific user."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    posts = db.query(Post).filter(Post.user_email == user.email).order_by(Post.created_at.desc()).all()
    all_posts = [
        {
            "post_id": p.id,
            "name": user.name,
            "username": user.username,
            "user_email": p.user_email,
            "text": p.text,
            "pfp": user.img,
            "img": p.img,
            "likes": get_likes_count(db, p.id),
            "comment_count": get_comments_count(db, p.id),
            "created_at": p.created_at.isoformat() if p.created_at else "",
        }
        for p in posts
    ]
    return {"posts": all_posts, "status": True}


# ──────────────────────────────────────────────
# Routes — Likes
# ──────────────────────────────────────────────

@app.post("/api/like-post")
async def like_post(
    data: LikeRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Toggle like on a post. Requires authentication."""
    existing = db.query(Like).filter(
        Like.post_id == data.post_id,
        Like.user_email == data.user_email,
    ).first()

    if existing:
        db.delete(existing)
        db.commit()
        return {"status": False, "message": "Like removed", "likes": get_likes_count(db, data.post_id)}

    new_like = Like(post_id=data.post_id, user_email=data.user_email)
    db.add(new_like)
    db.commit()
    return {"status": True, "message": "Post liked", "likes": get_likes_count(db, data.post_id)}


@app.post("/api/check-liked")
async def check_liked(data: CheckLikedRequest, db: Session = Depends(get_db)):
    """Check if a user has liked a specific post."""
    existing = db.query(Like).filter(
        Like.post_id == data.post_id,
        Like.user_email == data.user_email,
    ).first()
    return {"liked": existing is not None}


# ──────────────────────────────────────────────
# Routes — Comments
# ──────────────────────────────────────────────

@app.post("/api/create-comment")
async def create_comment(
    data: CommentCreate,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Add a comment to a post. Requires authentication."""
    post = db.query(Post).filter(Post.id == data.post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    new_comment = Comment(
        user_email=data.user_email,
        post_id=data.post_id,
        text=data.text,
        created_at=datetime.utcnow(),
        name=data.name or "",
    )
    db.add(new_comment)
    db.commit()
    return {"status": True, "message": "Comment added successfully"}


@app.post("/api/get-comments")
async def get_comments(data: GetCommentsRequest, db: Session = Depends(get_db)):
    """Get all comments for a post."""
    post = db.query(Post).filter(Post.id == data.post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    comments = (
        db.query(Comment)
        .filter(Comment.post_id == data.post_id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    all_comments = [
        {
            "name": c.name,
            "email": c.user_email,
            "text": c.text,
            "created_at": c.created_at.isoformat() if c.created_at else "",
        }
        for c in comments
    ]
    return {"status": True, "message": "Comments fetched", "comments": all_comments}


# ──────────────────────────────────────────────
# Routes — Follow System
# ──────────────────────────────────────────────

@app.post("/api/follow-user")
async def follow_user(
    data: FollowRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Follow a user. Requires authentication."""
    if data.follower_email == data.following_email:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    existing = db.query(Follow).filter(
        Follow.follower_email == data.follower_email,
        Follow.following_email == data.following_email,
    ).first()

    if existing:
        return {"status": False, "message": "Already following"}

    new_follow = Follow(
        follower_email=data.follower_email,
        following_email=data.following_email,
    )
    db.add(new_follow)
    db.commit()
    return {"status": True, "message": "Followed successfully"}


@app.post("/api/unfollow-user")
async def unfollow_user(
    data: FollowRequest,
    db: Session = Depends(get_db),
    auth: dict = Depends(verify_clerk_token),
):
    """Unfollow a user. Requires authentication."""
    existing = db.query(Follow).filter(
        Follow.follower_email == data.follower_email,
        Follow.following_email == data.following_email,
    ).first()

    if not existing:
        raise HTTPException(status_code=404, detail="Not following this user")

    db.delete(existing)
    db.commit()
    return {"status": True, "message": "Unfollowed successfully"}


@app.post("/api/check-following")
async def check_following(data: FollowRequest, db: Session = Depends(get_db)):
    """Check if a user is following another user."""
    existing = db.query(Follow).filter(
        Follow.follower_email == data.follower_email,
        Follow.following_email == data.following_email,
    ).first()
    return {"following": existing is not None}


@app.post("/api/get-followers")
async def get_followers(data: GetUserRequest, db: Session = Depends(get_db)):
    """Get follower and following counts for a user."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    followers = db.query(Follow).filter(Follow.following_email == user.email).count()
    following = db.query(Follow).filter(Follow.follower_email == user.email).count()
    return {"status": True, "followers": followers, "following": following}


@app.post("/api/get-follower-list")
async def get_follower_list(data: GetUserRequest, db: Session = Depends(get_db)):
    """Get the full list of users who follow a specific user."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Join with User table to get details of followers
    follower_rels = (
        db.query(User)
        .join(Follow, Follow.follower_email == User.email)
        .filter(Follow.following_email == user.email)
        .all()
    )

    result = [
        {"name": u.name, "username": u.username, "pfp": u.img, "email": u.email}
        for u in follower_rels
    ]
    return {"status": True, "users": result}


@app.post("/api/get-following-list")
async def get_following_list(data: GetUserRequest, db: Session = Depends(get_db)):
    """Get the full list of users whom a specific user follows."""
    user = db.query(User).filter(User.username == data.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Join with User table to get details of following
    following_rels = (
        db.query(User)
        .join(Follow, Follow.following_email == User.email)
        .filter(Follow.follower_email == user.email)
        .all()
    )

    result = [
        {"name": u.name, "username": u.username, "pfp": u.img, "email": u.email}
        for u in following_rels
    ]
    return {"status": True, "users": result}


# ──────────────────────────────────────────────
# Vercel Serverless Handler
# ──────────────────────────────────────────────

# For local development: uvicorn api.main:app --reload
# For Vercel: the app object is automatically picked up