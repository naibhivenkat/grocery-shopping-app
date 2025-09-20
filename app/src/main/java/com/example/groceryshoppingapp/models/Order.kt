
package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class Order(
    @SerializedName("order_uuid")
    val orderUuid: String,

    @SerializedName("customer")
    val customer: Customer,  // ✅ Use Customer object, not String

    @SerializedName("items")
    val items: List<ItemQuantity>,

    @SerializedName("status")
    val status: String,

    @SerializedName("created_at")
    val createdAt: String? = null,

    @SerializedName("shop_name")
    val shopName: String? = null
) : Parcelable


@Parcelize
data class ItemQuantity(
    @SerializedName("item_id")
    val itemId: String,

    val name: String,
    val price: Double,
    val quantity: Double
) : Parcelable




data class OrderItemRequest(
    val item_id: String,
    val quantity: Int
)

data class CreateOrderRequest(
    val shopId: String,
    val payment_method: String,
    val items: List<OrderItemRequest>
)


@Parcelize
data class Customer(
    val id: String,
    val username: String,
    val fullName: String? = null,
    val email: String? = null,
    val phone: String? = null
) : Parcelable
