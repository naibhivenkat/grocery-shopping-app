package com.example.groceryshoppingapp

data class CartItem(val id: Int, val itemName: String, val quantity: Int, val price: Float)
data class Order(val id: Int, val customerName: String, val status: String, val items: List<CartItem>)
data class ApiResponse(val status: String, val message: String)