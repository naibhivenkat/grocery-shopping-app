package com.example.groceryshoppingapp.network

import com.example.groceryshoppingapp.models.AddItemsRequest
import com.example.groceryshoppingapp.models.*
import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.POST
import retrofit2.http.FormUrlEncoded
import retrofit2.http.Field
import retrofit2.http.PATCH
import okhttp3.ResponseBody
import retrofit2.http.DELETE
import retrofit2.http.PUT
import retrofit2.http.Header



interface ApiService {
    @PATCH("api/orders/{order_id}")
    fun updateOrder(
        @Path("order_id") orderId: String,
        @Body body: Map<String, String>
    ): Call<Map<String, Any>>

    @GET("api/orders/{uuid}")
    fun getOrderById(@Path("uuid") uuid: String): Call<Order>

    @GET("shops")
    fun getAllShops(): Call<List<Shop>>


    @POST("cart/add")
    @FormUrlEncoded
    fun addToCart(
        @Field("customer_id") customerId: Int,
        @Field("item_id") itemId: String
    ): Call<ApiResponse>

    @GET("cart/{customer_id}")
    fun getCartItems(@Path("customer_id") customerId: Int): Call<List<CartItem>>

    @POST("order/place")
    @FormUrlEncoded
    fun placeOrder(
        @Field("customer_id") customerId: Int,
        @Field("shop_id") shopId: Int,
        @Field("payment_mode") paymentMode: String
    ): Call<ApiResponse>

    // Original per‑shop endpoint (can still be used)
    @GET("api/orders/shopkeeper/{shop_id}")
    fun getShopOrders(
        @Path("shop_id") shopId: String
    ): Call<List<Order>>

    // New multi‑shop endpoint using query params
//    @GET("api/orders/shopkeeper")
//    fun getShopOrdersMulti(@Query("shop_id") shopIds: List<String>): Call<List<Order>>


    @POST("order/{order_id}/status")
    @FormUrlEncoded
    fun updateOrderStatus(
        @Path("order_id") orderId: String,
        @Field("status") status: String,
        @Field("message") message: String? = null
    ): Call<ApiResponse>

    @GET("api/shops/shopkeeper/{shopkeeper_id}")
    fun getShopsForShopkeeper(@Path("shopkeeper_id") shopkeeperId: Int): Call<List<Shop>>


    @POST("login")
    fun login(@Body request: LoginRequest): Call<LoginResponse>

    @GET("api/orders/customer/{customer_id}")
    fun getCustomerOrders(@Path("customer_id") customerId: Int): Call<List<Order>>

    @POST("/change_password")
    fun changePassword(
        @Header("Authorization") auth: String,
        @Body body: Map<String, String>
    ): Call<Map<String, Any>>


    @POST("/update_profile")
    fun updateProfile(@Body profileData: Map<String, String>): Call<ResponseBody>

    @GET("api/shops/{shop_id}/items")
    fun getItems(
        @Header("Authorization") token: String,
        @Path("shop_id") shopId: String
    ): Call<GetItemsResponse>


    @POST("/shop/add_items")
    fun addItems(@Body request: AddItemsRequest): Call<ApiResponse>


    @PUT("/update_item/{item_id}")
    fun updateItem(
        @Path("item_id") itemId: String,
        @Body updateData: Map<String, String>
    ): Call<Map<String, Boolean>>

    @DELETE("/delete_item/{item_id}")
    fun deleteItem(@Path("item_id") itemId: String): Call<Map<String, Boolean>>

    @GET("api/shops/{shop_id}/items")
    fun getItemsForShop(
        @Header("Authorization") token: String,
        @Path(value = "shop_id", encoded = true) shopId: String
    ): Call<GetItemsResponse>

    @POST("send_otp")
    fun sendOtp(@Body body: Map<String, String>): Call<Map<String, String>>

    @POST("verify_otp")
    fun verifyOtp(@Body body: Map<String, String>): Call<Map<String, String>>

    @POST("register_after_otp")
    fun registerAfterOtp(@Body body: Map<String, String>): Call<RegisterResponse>

    @GET("/get_shop_by_owner")
    fun getShopByOwner(
        @Header("Authorization") authHeader: String,
        @Query("shopkeeperId") shopkeeperId: String
    ): Call<GetShopResponse>

}