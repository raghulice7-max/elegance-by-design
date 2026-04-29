from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from pydantic import BaseModel
import os
from typing import List, Optional
import razorpay

# Initialize FastAPI
app = FastAPI(title="Elegance by Design API")

# Setup CORS to allow requests from the frontend hosted on Netlify
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL", "your-supabase-url")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-supabase-anon-key")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize Razorpay client
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_SjKORzn6VQAltj")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "pmnUPFJ6pDRQX21LOQZQZ5Aw")
rzp_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Models
class OrderItem(BaseModel):
    product_id: int
    quantity: int
    price: float
    size: str = "Standard"

class CheckoutRequest(BaseModel):
    user_id: str
    items: List[OrderItem]
    subtotal: float
    shipping: float
    discount: float
    total: float
    payment_method: str
    delivery_info: dict

# Dependency to verify user token via Supabase Auth
def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ")[1]
    
    # Verify the token with Supabase
    try:
        user = supabase.auth.get_user(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication error: {str(e)}")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Welcome to Elegance by Design API!"}

@app.get("/api/products")
def get_products():
    """Fetch all products from the database."""
    response = supabase.table("products").select("*").execute()
    return response.data

@app.get("/api/products/{category}")
def get_products_by_category(category: str):
    """Fetch products by category."""
    response = supabase.table("products").select("*").eq("category", category).execute()
    return response.data

@app.post("/api/checkout")
def process_checkout(checkout_data: CheckoutRequest, user=Depends(verify_token)):
    """Process an order checkout securely."""
    # 1. Insert order into the database
    order_insert = supabase.table("orders").insert({
        "user_id": checkout_data.user_id,
        "subtotal": checkout_data.subtotal,
        "shipping": checkout_data.shipping,
        "discount": checkout_data.discount,
        "total": checkout_data.total,
        "payment_method": checkout_data.payment_method,
        "delivery_info": checkout_data.delivery_info,
        "status": "pending"
    }).execute()
    
    if not order_insert.data:
        raise HTTPException(status_code=500, detail="Failed to create order")
        
    order_id = order_insert.data[0]["id"]
    
    # 2. Insert order items
    order_items = []
    for item in checkout_data.items:
        order_items.append({
            "order_id": order_id,
            "product_id": item.product_id,
            "quantity": item.quantity,
            "size": item.size,
            "price_at_purchase": item.price
        })
        
    supabase.table("order_items").insert(order_items).execute()
    
    # 3. Clear user's cart
    supabase.table("cart_items").delete().eq("user_id", checkout_data.user_id).execute()
    
    return {"message": "Order processed successfully", "order_id": order_id}

@app.get("/api/orders")
def get_user_orders(user=Depends(verify_token)):
    """Fetch orders for the logged in user."""
    user_id = user.user.id 
    response = supabase.table("orders").select("*, order_items(*, products(*))").eq("user_id", user_id).execute()
    return response.data

class PaymentOrderRequest(BaseModel):
    amount: float

@app.post("/api/create-payment-order")
def create_payment_order(request: PaymentOrderRequest, user=Depends(verify_token)):
    """Generate a Razorpay Order ID for checkout."""
    amount_in_paise = int(request.amount * 100)
    order_data = {
        "amount": amount_in_paise,
        "currency": "INR",
        "receipt": f"receipt_{user.user.id[:8]}",
        "payment_capture": 1
    }
    try:
        razorpay_order = rzp_client.order.create(data=order_data)
        return {"order_id": razorpay_order["id"], "amount": amount_in_paise, "currency": "INR"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
