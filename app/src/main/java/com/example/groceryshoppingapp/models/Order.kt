
package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class Order(
    @SerializedName("order_uuid")
    val orderUuid: String,

    @SerializedName("customer")
    val customerName: String,

    @SerializedName("items")
    val items: List<ItemQuantity>,

    @SerializedName("status")
    val status: String,

    // Optional fields — set as nullable or default
    @SerializedName("created_at")
    val createdAt: String? = null,

    @SerializedName("shop_name")
    val shopName: String? = null
) : Parcelable

@Parcelize
data class ItemQuantity(
    val item: Item,
    val quantity: Int
) : Parcelable

