package com.example.groceryshoppingapp.models

data class ShopOrder(
    val orderId: Int,
    val customerName: String,
    val items: List<OrderItem>,
    val status: String
)

data class OrderItem(
    val name: String,
    val quantity: Int
)