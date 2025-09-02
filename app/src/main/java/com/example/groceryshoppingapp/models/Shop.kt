package com.example.groceryshoppingapp.models

data class Shop(
    val id: String,
    val name: String,
    val address: String,
    val contact: String,
    val shopkeeper_id: Int
)


//data class ShopResponse(
//    val success: Boolean,
//    val shop: Shop?
//)