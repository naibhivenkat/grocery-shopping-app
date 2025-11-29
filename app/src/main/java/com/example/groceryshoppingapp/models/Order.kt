package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class Order(
    @SerializedName("order_uuid")
    val orderUuid: String,

    @SerializedName("customer")
    val customer: Customer,  // object, not String

    @SerializedName("items")
    val items: List<ItemQuantity>,

    @SerializedName("status")
    val status: String,

    @SerializedName("created_at")
    val createdAt: String? = null,

    @SerializedName("shopId")
    val shopId: String? = null,   // ✅ fixed key

    @SerializedName("shop_name")
    val shopName: String? = null,

    @SerializedName("total")
    val total: Double? = null,    // ✅ added total

    @SerializedName("payment_method")
    val payment_method: String? = null,  // 🔹 new

    @SerializedName("transaction_id")
    val transaction_id: String? = null,   // 🔹 new optional

    @SerializedName("invoice_url")
    val invoiceUrl: String? = null,

    @SerializedName("partial_refund_amount")
    val partialRefundAmount: Double? = null,

    @SerializedName("partial_items")
    val shortageItems: List<ShortageItem>? = null



) : Parcelable

@Parcelize
data class ItemQuantity(
    @SerializedName("item_id")
    val itemId: String,

    val name: String,
    var price: Double,
    var quantity: Double,
    var comment: String? = null,
    @SerializedName("original_quantity")
    var originalQuantity: Double = 0.0

) : Parcelable

data class OrderItemRequest(
    val item_id: String,
    val quantity: Double
)

data class CreateOrderRequest(
    val shopId: String,
    val payment_method: String,
    val items: List<OrderItemRequest>,
    val transaction_id: String? = null, // 🔹 optional
    val invoice_url: String? = null
)

@Parcelize
data class Customer(
    val id: String,
    val username: String,
    val fullName: String? = null,
    val email: String? = null,
    val phone: String? = null
) : Parcelable
