package com.example.groceryshoppingapp.models

import com.google.gson.annotations.SerializedName

data class AddItemsRequest(
    @SerializedName("shop_id")
    val shopId: String,
    val items: List<Item>
)
