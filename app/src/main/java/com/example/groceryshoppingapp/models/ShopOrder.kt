package com.example.groceryshoppingapp.models

import android.os.Parcelable
import kotlinx.parcelize.Parcelize

data class ShopOrder(
    val orderId: Int,
    val customerName: String,
    val items: List<OrderItem>,
    val status: String
)

@Parcelize
data class OrderItem(
    val name: String,
    var quantity: Int,
    var price: Double,
    var comment: String? = null
) : Parcelable