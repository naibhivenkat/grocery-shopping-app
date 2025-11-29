package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class ShortageItem(
    @SerializedName("item_id") val itemId: String,
    @SerializedName("name") val name: String?,
    @SerializedName("original_quantity") val orderedQty: Double,
    @SerializedName("delivered_quantity") val deliveredQty: Double,
    @SerializedName("refund_amount") val refundAmount: Double
) : Parcelable
