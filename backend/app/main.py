from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.database.database import init_database

<<<<<<< HEAD

init_database()


=======
init_database()

>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
app = FastAPI(
    title="NEXUS API",
    description="Intelligent Electrical Monitoring System API",
    version="0.1.0",
)

<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

<<<<<<< HEAD

=======
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
app.include_router(router)


@app.get("/")
def root():
    return {
        "name": "NEXUS",
        "description": "Intelligent Electrical Monitoring System",
        "version": "0.1.0",
        "status": "operational",
    }


@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "service": "nexus-api",
<<<<<<< HEAD
    }
=======
    }
>>>>>>> 02fde370763d1c188b8feb2264e406ee5aafbdac
