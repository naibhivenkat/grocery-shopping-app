package com.example.groceryshoppingapp.models

data class OrderResponse(
    val success: Boolean,
    val orderId: Int,
    val message: String
)
