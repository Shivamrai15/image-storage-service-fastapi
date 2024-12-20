from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import google.auth
import google.oauth2.id_token
from google.auth.transport import requests
from google.cloud import firestore, storage
import starlette.status as status
from datetime import datetime
import local_constants
import hashlib

app = FastAPI()


app.mount('/static', StaticFiles(directory='static'), name='static' )
templets = Jinja2Templates(directory='templates')

firestore_db = firestore.Client()
firebase_request_adapter = requests.Request()

@app.get("/", response_class=HTMLResponse)
async def root( request : Request ) :
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    getUser(user_token)
    gallery =  getUserGalleries(user_token['user_id'])
    galleryImages = getGalleryFirstImages(gallery)
    return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : user_token , 'error_message' : error_message, "gallery" : gallery, "galleryImages": galleryImages })
    

def validateFirebaseToken(id_token):
    if not id_token:
        return None
    
    user_token = None
    try:
        user_token = google.oauth2.id_token.verify_firebase_token(id_token, firebase_request_adapter)
    except ValueError as err:
        print(str(err))
    return  user_token


def getUser(user_token):
    user = firestore_db.collection('users').document(user_token['user_id']).get()
    if not user.exists:   
        firestore_db.collection('users').document(user_token['user_id']).create({
            "email" : user_token['email'],
            "createdAt" : datetime.now()
        })
        user = firestore_db.collection('users').document(user_token['user_id']).get()
    return user


def addFile(file):
    storage_client = storage.Client( project = local_constants.PROJECT_NAME )
    bucket = storage_client.bucket(local_constants.PROJECT_STORAGE_BUCKET)
    blob = storage.Blob(file.filename, bucket)
    blob.upload_from_file(file.file)
    blob.make_public()
    return blob.public_url


def getUserGalleries (userId):
    try:
        existedGalleries = firestore_db.collection('gallery').where('userId', "==", userId).get()
        return existedGalleries
    except:
        return []


def getGalleryFirstImages( galleries ):
    
    images = {}
    if len(galleries) == 0:
        return images
    
    for gallery in galleries:
        image = firestore_db.collection('images').where("galleryId", "==", gallery.id).order_by("createdAt", "ASCENDING").limit(1).get()
        if image:
            images.update({ gallery.id: image[0].get("image") })
    return images


def getGalleryImages ( galleryId : str ) :
    try:
        images = firestore_db.collection('images').where('galleryId', "==", galleryId).get()
        if len(images) == 0:
            return None
        return images
    except:
        return None


def imageHash (file):
    hasher = hashlib.md5()
    content = file.file.read()
    hasher.update(content)
    file.file.seek(0)
    return hasher.hexdigest()


def findDuplicates (images) :
    duplicates = set()
    visited = set()
    if images:
        for image in images:
            hash = image.get("hash")
            if hash in visited:
                duplicates.add(image)
            else:
                visited.add(hash)
    
    if len(duplicates) == 0:
        duplicates = None
    del(visited)
    return duplicates


@app.post("/create-gallery", response_class=HTMLResponse)
async def createGallery( request:Request ):
    try:
        id_token = request.cookies.get("token")
        error_message = "No error here"
        user_token = None
        user_token = validateFirebaseToken(id_token)
        if not user_token :
            return RedirectResponse("/")
        
        form = await request.form()
        existedGalleries = getUserGalleries(user_token['user_id'])
        for gallery in existedGalleries:
            if gallery.get("name") == form['name']:
                return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

        firestore_db.collection('gallery').document().set({
            "name" : form['name'],
            "userId" : user_token['user_id'],
            "createdAt" : datetime.now(),
            "allowedUsers" : []
        })
        return RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    except Exception as e:
        print("Exception", e)
        return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.get("/gallery/{id}")
async def getGallery( request : Request, id:str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    gallery = firestore_db.collection('gallery').document(id).get()
    if not gallery.exists:
        return RedirectResponse("/")

    if (gallery.get('userId') != user_token['user_id']) and ( user_token['email'] not in gallery.get("allowedUsers")  ) :
        return RedirectResponse("/")
    
    images = getGalleryImages(galleryId=gallery.id)
    imagesOfEachGallery = firestore_db.collection("images").where("userId", "==", user_token['user_id']).get()
    imagesList = []
    for image in imagesOfEachGallery:
        if image.get("galleryId") != id:
            imagesList.append(image)

    duplicates = findDuplicates(images)
    entireDuplicates = set()
    if images and len(imagesList) != 0:
        imagesHash = set()
        for image in images:
            imagesHash.add(image.get("hash"))
        for image in imagesList:
            if image.get("hash") in imagesHash:
                entireDuplicates.add(image)

    if len(entireDuplicates) == 0:
        entireDuplicates = None

    return templets.TemplateResponse('gallery.html', { 'request' : request, 'user_token': user_token, "gallery": gallery, "images": images, "duplicates": duplicates, "entireDuplicates": entireDuplicates })



@app.get("/gallery/update/{id}")
async def getGallery( request : Request, id:str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })

    gallery = firestore_db.collection('gallery').document(id).get()
    if not gallery.exists:
        return RedirectResponse("/")

    if gallery.get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    
    return templets.TemplateResponse('update-gallery.html', { 'request' : request, 'user_token': user_token, "gallery": gallery })



@app.post("/gallery/update/{id}")
async def updateGallery( request : Request, id:str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })

    
    form = await request.form()
    existedGalleries = getUserGalleries(user_token['user_id'])
    for gallery in existedGalleries:
            if gallery.get("name") == form['name']:
                return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


    gallery = firestore_db.collection('gallery').document(id)
    if not gallery.get().exists:
        return RedirectResponse("/")

    if gallery.get().get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    
    gallery.update({
        "name" : form['name']
    })
    
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


@app.get("/gallery/delete/{id}", response_class=RedirectResponse)
async def deleteGallery ( request: Request, id: str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    gallery = firestore_db.collection('gallery').document(id)
    if not gallery.get().exists:
        return RedirectResponse("/")

    if gallery.get().get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    
    gallery.delete()

    return RedirectResponse("/")


@app.post("/upload/{id}", response_class=RedirectResponse)
async def uploadImage ( request: Request, id: str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    gallery = firestore_db.collection('gallery').document(id)
    if not gallery.get().exists:
        return RedirectResponse("/")
    
    form = await request.form()
    hash = imageHash(form['image'])
    url = addFile(form['image'])

    firestore_db.collection('images').document().set({
        "image" : url,
        "filename" : form['image'].filename,
        "galleryId" : id,
        "userId" : user_token['user_id'],
        "hash" : hash,
        "createdAt" : datetime.now()
    })
    
    return RedirectResponse(f"/gallery/{id}", status_code=status.HTTP_302_FOUND)


@app.get("/delete-image/{id}", response_class=RedirectResponse)
async def deleteImage( request: Request, id:str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    image = firestore_db.collection('images').document(id)
    if not image.get().exists:
        return RedirectResponse("/")
    
    if image.get().get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    
    galleryId = image.get().get("galleryId")
    image.delete()

    return RedirectResponse(f"/gallery/{galleryId}", status_code=status.HTTP_302_FOUND)


@app.get("/share/{id}", response_class=HTMLResponse)
async def sharePage(request: Request, id:str):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    gallery = firestore_db.collection('gallery').document(id).get()
    if not gallery.exists:
        return RedirectResponse("/")
    
    if gallery.get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    

    return templets.TemplateResponse('share.html', { 'request' : request, 'user_token': user_token, "gallery": gallery})



@app.post("/share/allow/{id}", response_class=RedirectResponse)
async def shareGallery( request: Request, id:str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    gallery = firestore_db.collection('gallery').document(id)
    if not gallery.get().exists:
        return RedirectResponse("/")
    
    if gallery.get().get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    
    form = await request.form()

    allowedUsers = set(gallery.get().get("allowedUsers"))
    allowedUsers.add(form['email'])
    gallery.update({"allowedUsers": allowedUsers}) 

    return RedirectResponse(f"/share/{id}", status_code=status.HTTP_302_FOUND)


@app.post("/share/restrict/{id}", response_class=RedirectResponse)
async def shareGallery( request: Request, id:str ):
    id_token = request.cookies.get("token")
    error_message = None
    user_token = None
    user_token = validateFirebaseToken(id_token)

    if not user_token:
        return templets.TemplateResponse('main.html', { 'request' : request, 'user_token' : None , 'error_message' : error_message, 'user_info': None })
    
    gallery = firestore_db.collection('gallery').document(id)
    if not gallery.get().exists:
        return RedirectResponse("/")
    
    if gallery.get().get('userId') != user_token['user_id']:
        return RedirectResponse("/")
    
    form = await request.form()

    allowedUsers = set(gallery.get().get("allowedUsers"))
    if form['email'] in allowedUsers:
        allowedUsers.remove(form['email'])
        gallery.update({"allowedUsers": allowedUsers}) 

    return RedirectResponse(f"/share/{id}", status_code=status.HTTP_302_FOUND)
    