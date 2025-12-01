package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@Parcelize
data class KhataAccount(
    @SerializedName("doc_id") var docId: String? = null,
    @SerializedName("shop_id") var shopId: String? = null,
    @SerializedName("customer_id") var customerId: String? = null,
    @SerializedName("customer_name") var customerName: String? = null,
    @SerializedName("phone") var phone: String? = null,
    @SerializedName("balance") var balance: Double? = 0.0,
    @SerializedName("updated_at") var updatedAt: String? = null
) : Parcelable

data class KhataAccountsResponse(
    val success: Boolean,
    val accounts: List<KhataAccount>?
)
