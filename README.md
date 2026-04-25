# VibeShare Backend — FastAPI

The engine behind the Digital Pulse. This backend provides a high-performance REST API with real-time hashtag analytics, secure social graph management, and automated media handling.

## 🚀 Core Technologies

- **FastAPI**: Modern, high-concurrency Python framework.
- **SQLAlchemy**: Powerful ORM for database abstraction.
- **Clerk Auth**: Secure JWT-based session validation.
- **Cloudinary**: Cloud-native image storage and transformation.
- **PostgreSQL**: Reliable relational data storage.
- **Vercel**: Optimized for serverless deployment.

## 🛠️ API Documentation

### Posts & Interactions
- `GET  /api/get-posts`: Retrieve all pulses with like and comment counts.
- `POST /api/create-post` (Auth): Share a new pulse with optional image upload (Cloudinary).
- `POST /api/delete-post` (Auth): Securely remove a pulse.
- `POST /api/like-post` (Auth): Toggle engagement on any pulse.

### Social System
- `POST /api/follow-user` (Auth): Connect with another user.
- `POST /api/unfollow-user` (Auth): Disconnect from a user.
- `POST /api/search-users`: Find users by name or username.
- `GET  /api/get-featured`: Get random user suggestions for "Suggested Orbits".

### Analytics & Comments
- `GET  /api/get-trending-tags`: Get the most frequent hashtags from pulses and comments.
- `POST /api/create-comment` (Auth): Add a comment to any pulse.
- `POST /api/get-comments`: Retrieve all conversation threads for a post.

## ⚙️ Configuration

Create a `.env` file in the root directory:

```env
DATABASE_URL=postgresql://...
CLERK_SECRET_KEY=sk_test_...
CLERK_JWKS_URL=https://.../.well-known/jwks.json
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

## 🏗️ Local Development

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Server**:
   ```bash
   uvicorn api.main:app --reload
   ```

3. **Verify**:
   Visit `http://localhost:8000/api/health` to check the system status.

## ☁️ Deployment

The backend is pre-configured for **Vercel** via `vercel.json`.
- Each request is handled by an edge-optimized serverless function.
- Media is processed off-thread via Cloudinary to maintain low latency.
- Ensure all environment variables are added to your Vercel project settings.

---
Developed for the **VibeShare** ecosystem.
