package com.example.groceryshoppingapp


data class Item(val id: Int,
                val name: String,
                val price: Double,
                val stockQuantity: Int,
                val description: String,
                val shopid: String)
data class CartItem(val id: Int, val itemName: String, val quantity: Int, val price: Float)
data class Order(val id: Int, val customerName: String, val status: String, val items: List<CartItem>)
data class ApiResponse(val status: String, val message: String)